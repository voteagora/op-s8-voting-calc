import click
import csv, os
from pathlib import Path
from yaml import load, FullLoader
from pprint import pprint
import json
from copy import deepcopy

from .jsonrpc_client import JsonRpcHistHttpClient
from .graphqleas_client import EASGraphQLClient
from .utils import load_config, get_web3
from web3 import Web3
from collections import defaultdict

from eth_abi import decode as decode_abi

from abifsm import ABISet, ABI
from .utils import camel_to_snake
from .signatures import *

from .attestations import meta as all_meta

import pandas as pd

DATA_DIR = Path(os.getenv('S8_DATA_DIR', 'op_s8_vote_calc/data'))
DEPLOYMENT = os.getenv('S8_DEPLOYMENT', 'test')

onchain_config, offchain_config = load_config()
PTC_MODULES = {v['address'] : v['name'] for v in onchain_config['gov']['modules']}

class Proposal:

    @property
    def title(self):
        description = self.row.get('description', None)
        return description.split("\n")[0]

    @property
    def proposal_type_label(self):
        if 'friendly_name' in self.proposal_type_info:
            return self.proposal_type_info['friendly_name']
        return self.proposal_type_info['module_name']


    def __str__(self):
        return f"{self.emoji} {self.proposal_type_label.upper()}: id={self.id}, title={self.title}"

    def load_meta(self):

        self.gov_address = onchain_config['gov']['address']
        self.ptc_address = onchain_config['ptc']['address']

        onchain_meta = json.load(open(DATA_DIR / DEPLOYMENT / (self.id + '.json'), 'r'))

        self.proposal_type_info = onchain_meta['proposal_type_info']
        self.quorum = onchain_meta['quorum']
        self.votable_supply = onchain_meta['votable_supply']
        self.asof_block_num = onchain_meta['asof_block_num']
        self.proposal_type_id = onchain_meta['proposal_type_id']
        self.counting_mode = onchain_meta['counting_mode']

def bte(x):
    return "✅" if x else "❌"


class StandardTally:

    def __init__(self, eligible_votes, quorum_thresh_pct, approval_thresh_pct, against_votes=0, for_votes=0, abstain_votes=0, include_abstain=False):
        """
        eligible_votes: Number of eligible voters (for off-chain) or Votable Supply (for on-chain)
        
        quorum_thresh_pct: Quorum threshold percentage as a float.  Eg. 0.5 for 50%
        approval_thresh_pct: Approval threshold percentage as a float.  Eg. 0.5 for 50%

        against_votes: Number of against votes (for off-chain) or VP against (for on-chain)
        for_votes: Number of for votes (for off-chain) or VP for (for on-chain)
        abstain_votes: Number of abstain votes (for off-chain) or VP abstain (for on-chain)
        """

        self.for_votes = for_votes
        self.against_votes = against_votes
        self.abstain_votes = abstain_votes

        self.include_abstain = include_abstain

        if self.include_abstain:
            self.total_votes = against_votes + for_votes + abstain_votes
        else:
            self.total_votes = against_votes + for_votes
    
        self.eligible_votes = eligible_votes

        self.quorum_thresh_pct = quorum_thresh_pct
        self.approval_thresh_pct = approval_thresh_pct

        if self.total_votes != 0:

            assert self.eligible_votes != 0, "eligible_votes must be non-zero, there should be no reason it's not."

            self.relative_for_pct = self.for_votes / self.total_votes
            self.relative_against_pct = self.against_votes / self.total_votes
            self.relative_abstain_pct = self.abstain_votes / self.total_votes

            self.absolute_for_pct = self.for_votes / self.eligible_votes
            self.absolute_against_pct = self.against_votes / self.eligible_votes
            self.absolute_abstain_pct = self.abstain_votes / self.eligible_votes

            self.quorum = self.total_votes / self.eligible_votes
            self.passing_quorum = self.quorum >= self.quorum_thresh_pct

            self.approval = self.for_votes / self.total_votes
            self.passing_approval_threshold = self.approval >= self.approval_thresh_pct

        else:
            self.relative_for_pct = 0
            self.relative_against_pct = 0
            self.relative_abstain_pct = 0
            self.absolute_for_pct = 0
            self.absolute_against_pct = 0
            self.absolute_abstain_pct = 0
            self.quorum = 0
            self.approval = 0

            self.passing_quorum = self.quorum >= self.quorum_thresh_pct
            self.passing_approval_threshold = self.approval >= self.approval_thresh_pct

    def gen_tally_report(self, label, weight=1):

        tally = f"{label} Tally"
        
        if weight < 1:
            tally += f" [{weight:.2%} of Final]\n"
        else:
            tally += "\n"

        tally += "-" * (len(tally) - 1) + "\n"


        tally += f"Total:    {self.total_votes:>32}\n"
        tally += f"Eligible: {self.eligible_votes:>32}\n"

        tally += f"For:      {self.for_votes:>32} ({self.relative_for_pct:.1%} of total | {self.absolute_for_pct:.1%} of eligible)\n"
        tally += f"Against:  {self.against_votes:>32} ({self.relative_against_pct:.1%} of total | {self.absolute_against_pct:.1%} of eligible)\n"

        if self.include_abstain:
            tally += f"Abstain:  {self.abstain_votes:>32} ({self.relative_abstain_pct:.1%} of total | {self.absolute_abstain_pct:.1%} of eligible)\n"

        tally += f"Quorum: {self.quorum:.2%} {bte(self.passing_quorum)} ({self.quorum_thresh_pct:.0%}), Approval: {self.approval:.2%} {bte(self.passing_approval_threshold)} ({self.approval_thresh_pct:.0%}) -> "

        if self.passing_quorum and self.passing_approval_threshold:
            tally += "✅ PASSING\n"
        else:
            tally += "❌ DEFEATED\n"

        return tally


class Choice(StandardTally):

    def __init__(self, label, eligible_votes, quorum_thresh_pct, approval_thresh_pct, votes, include_abstain=False):

        self.label = label

        against_votes = int(votes.get(0, 0))
        for_votes = int(votes.get(1, 0))
        abstain_votes = int(votes.get(2, 0)) if include_abstain else 0

        super().__init__(eligible_votes, quorum_thresh_pct, approval_thresh_pct, against_votes, for_votes, abstain_votes, include_abstain)


class ApprovalTally:

    def __init__(self, eligible_votes, quorum_thresh_pct, approval_thresh_pct, counts, total_voting_vp, include_abstain=False):
        """
        eligible_votes: Number of eligible voters (for off-chain) or Votable Supply (for on-chain)
        
        quorum_thresh_pct: Quorum threshold percentage as a float.  Eg. 0.5 for 50%
        approval_thresh_pct: Approval threshold percentage as a float.  Eg. 0.5 for 50%

        votes: Dictionary of choices with votes, where the key is the choice, and then sub-keys are for
        against, for, abstain.  eg.

        {'choice 1' : {'0' : 10, '1' : 20, '2' : 30},
         'choice 2' : {'0' : 10, '1' : 20, '2' : 30}}

        """

        self.choice_tallies = {k : Choice(k, eligible_votes, quorum_thresh_pct, approval_thresh_pct, v, include_abstain) for k, v in counts.items()}

        self.include_abstain = include_abstain

        if self.include_abstain:
            self.total_votes = sum([int(v) for v in total_voting_vp.values()])
        else:
            self.total_votes = sum([int(v) for k, v in total_voting_vp.items() if k in [0, 1]])
    
        self.eligible_votes = eligible_votes

        self.quorum_thresh_pct = quorum_thresh_pct
        self.approval_thresh_pct = approval_thresh_pct

        if self.total_votes != 0:

            assert self.eligible_votes != 0, "eligible_votes must be non-zero, there should be no reason it's not."

            self.relative_pct = {k : {support : int(vp) / self.total_votes for support, vp in v.items()} for k, v in counts.items()}

            self.absolute_pct = {k : {support : int(vp) / self.eligible_votes for support, vp in v.items()} for k, v in counts.items()}

            self.quorum = self.total_votes / self.eligible_votes
            self.passing_quorum = self.quorum >= self.quorum_thresh_pct

            self.approval = {k : int(v.get(1, 0)) / self.total_votes for k, v in counts.items()}
            self.passing_approval_threshold = {k : a >= self.approval_thresh_pct for k, a in self.approval.items()}

        else:
            self.relative_for_pct = 0
            self.relative_against_pct = 0
            self.relative_abstain_pct = 0
            self.absolute_for_pct = 0
            self.absolute_against_pct = 0
            self.absolute_abstain_pct = 0
            self.quorum = 0
            self.approval = 0

            self.passing_quorum = self.quorum >= self.quorum_thresh_pct
            self.passing_approval_threshold = self.approval >= self.approval_thresh_pct

    def gen_tally_report(self, label, weight=1):

        tally = f"{label} Tally"
        
        if weight < 1:
            tally += f" [{weight:.2%} of Final]\n"
        else:
            tally += "\n"

        tally += "-" * (len(tally) - 1) + "\n"


        tally += f"Given {self.total_votes} total votes, and {self.eligible_votes} eligible votes... \n"

        for k, choice in self.choice_tallies.items():
            if choice.label == -1 and self.include_abstain:
                tally += f"Abstain: {choice.abstain_votes} ({choice.abstain_votes / self.total_votes:.1%} of total | {choice.absolute_abstain_pct:.1%} of eligible)\n"
            else:
                tally += f"For: {choice.for_votes} {bte(self.passing_approval_threshold[choice.label])} ({self.approval[choice.label]:.1%} of total | {choice.absolute_for_pct:.1%} of eligible)\n"
        
        tally += f"Quorum: {self.quorum:.2%} {bte(self.passing_quorum)} ({self.quorum_thresh_pct:.0%})"

        return tally




class FinalTally:
    def __init__(self, tallies, weights, quorum_thresh_pct, approval_thresh_pct, include_abstain=False):
        self.tallies = tallies
        self.weights = weights

        self.relative_for_pct = sum([t.relative_for_pct * w for t, w in zip(tallies, weights)])
        self.relative_against_pct = sum([t.relative_against_pct * w for t, w in zip(tallies, weights)])
        self.relative_abstain_pct = sum([t.relative_abstain_pct * w for t, w in zip(tallies, weights)])

        self.absolute_for_pct = sum([t.absolute_for_pct * w for t, w in zip(tallies, weights)])
        self.absolute_against_pct = sum([t.absolute_against_pct * w for t, w in zip(tallies, weights)])
        self.absolute_abstain_pct = sum([t.absolute_abstain_pct * w for t, w in zip(tallies, weights)])

        self.quorum = sum([t.quorum * w for t, w in zip(tallies, weights)])
        self.approval = sum([t.approval * w for t, w in zip(tallies, weights)])

        self.quorum_thresh_pct = quorum_thresh_pct
        self.approval_thresh_pct = approval_thresh_pct
   
        self.passing_quorum = self.quorum >= quorum_thresh_pct
        self.passing_approval_threshold = self.approval >= approval_thresh_pct     

        self.include_abstain = include_abstain


    def gen_tally_report(self, label):

        tally = f"{label} Tally\n"
        tally += "-" * (len(tally) - 1) + "\n"

        tally += f"For: ({self.relative_for_pct:.1%} of total | {self.absolute_for_pct:.1%} of eligible)\n"
        tally += f"Against: ({self.relative_against_pct:.1%} of total | {self.absolute_against_pct:.1%} of eligible)\n"

        if self.include_abstain:
            tally += f"Abstain: ({self.relative_abstain_pct:.1%} of total | {self.absolute_abstain_pct:.1%} of eligible)\n"

        tally += f"Quorum: {self.quorum:.3%} {bte(self.passing_quorum)} ({self.quorum_thresh_pct:.0%}), Approval: {self.approval:.3%} {bte(self.passing_approval_threshold)} ({self.approval_thresh_pct:.0%}) -> "

        if self.passing_quorum and self.passing_approval_threshold:
            tally += "✅ PASSING\n"
        else:
            tally += "❌ DEFEATED\n"

        return tally


class OffChain(Proposal):
    emoji = '⛓️‍💥'
    def __init__(self, row):
        self.row = row.to_dict()
        self.offchain_proposal_id = self.row['proposalId']
        self.id = self.offchain_proposal_id
        self.proposal_type_id = self.row['proposal_type_id']
        self.calculation_options = self.row.get('calculation_options', 0)
        assert self.calculation_options in [0, 1], f"Invalid calculation options: {self.calculation_options}"
        self.include_abstain = self.calculation_options == 0

        self.proposal_type_info = {}
        
        self.proposal_type_info['friendly_name'] = self.row['proposal_type']
        if 'tiers' in self.row:
            self.proposal_type_info['tiers'] = self.row['tiers']

        self.load_meta()


    def load_context(self):

        # Assumed hard-coded for now.
        self.ch_counts = {'app' : 100, 'user': 1000, 'chain' : 15}

        citizens = pd.read_csv(DATA_DIR / DEPLOYMENT / "Citizens.csv")

        # Filter out non-compliant attestations.
        citizens = citizens[citizens['SelectionMethod'].isin(['5.1', '5.2', '5.3'])]
        citizens['SelectionMethod'] = citizens['SelectionMethod'].map({'5.1': 'chain', '5.2': 'app', '5.3': 'user'})
 
        df = pd.read_csv(DATA_DIR / DEPLOYMENT / 'Vote.csv')

        offc_votes = df[df['proposalId'] == self.offchain_proposal_id].copy()
        offc_votes['support'] = offc_votes['params'].apply(lambda x: json.loads(x)[0])
        offc_votes['weight'] = 1

        offc_votes = offc_votes[offc_votes['refUID'].isin(citizens[~citizens['revoked']]['id'])].copy()

        if offc_votes.duplicated(subset=['refUID']).any():
            raise ValueError("Duplicates found in offc_votes.refUID.")

        if citizens.duplicated(subset=['id']).any():
            raise ValueError("Duplicates found in citizens.id.")

        offc_votes_with_citizens = offc_votes.merge(citizens, left_on='refUID', right_on='id', how='inner', validate='one_to_one')

        offc_votes_with_citizens = offc_votes_with_citizens[['SelectionMethod', 'support', 'weight']].copy()

        self.offc_votes = offc_votes_with_citizens        

    def calculate_standard_tallies(self):
        
        assert self.proposal_type_label == 'basic', f"Proposal type is not basic: {self.proposal_type_label}"

        def bigint_sum(arr):
            return str(sum([int(o) for o in arr.values]))

        counts = self.offc_votes.groupby(['SelectionMethod', 'support'])['weight'].sum()
        
        empty = pd.Series(dtype='int64', name='weight')
        empty.index.name = 'support'

        tallies = []

        for category in ['app', 'user', 'chain']:
            cat_counts = counts.get(category, empty).to_dict(into=defaultdict(int))

            approval_thresh_pct = (self.proposal_type_info['approval_threshold_bps'] / 10000)
            quorum_thresh_pct =  (self.proposal_type_info['quorum_bps'] / 10000)

            eligible_votes = self.ch_counts[category]
            
            tally = StandardTally(eligible_votes, quorum_thresh_pct, approval_thresh_pct, cat_counts[0], cat_counts[1], cat_counts[2], include_abstain=self.include_abstain)
            tallies.append(tally)
        
        return tallies

    def show_result(self):

        weights = [1/3, 1/3, 1/3]

        print()
        print(self)
        print()

        tallies = self.calculate_standard_tallies()

        print(tallies[0].gen_tally_report("Citizen House - Apps", weights[0]))
        print(tallies[1].gen_tally_report("Citizen House - Users", weights[1]))
        print(tallies[2].gen_tally_report("Citizen House - Chains", weights[2]))

        quorum_thresh_pct = tallies[0].quorum_thresh_pct
        approval_thresh_pct = tallies[0].approval_thresh_pct

        for i, t in enumerate(tallies):
            assert t.quorum_thresh_pct == quorum_thresh_pct, f"Quorum PCTs do not match: {t.quorum_thresh_pct} != {quorum_thresh_pct} for tally {i}"
            assert t.approval_thresh_pct == approval_thresh_pct, f"Approval Threshold PCTs do not match: {t.approval_thresh_pct} != {approval_thresh_pct} for tally {i}"

        final_tally = FinalTally(tallies, weights = weights, quorum_thresh_pct = quorum_thresh_pct, approval_thresh_pct = approval_thresh_pct, include_abstain=self.include_abstain)
        print(final_tally.gen_tally_report("Final"))

class OnChain(Proposal):
    emoji = '⛓️'
    def __init__(self, row):
        self.row = row.to_dict()
        self.id = self.row['proposal_id']
        self.onchain_proposal_id = self.id

        self.load_meta()

        self.include_abstain = 'abstain' in self.counting_mode

    def load_context(self):

        df1 = pd.read_csv(DATA_DIR / DEPLOYMENT / 'VoteCast(address,uint256,uint8,uint256,string).csv')
        df2 = pd.read_csv(DATA_DIR / DEPLOYMENT / 'VoteCastWithParams(address,uint256,uint8,uint256,string,bytes).csv')
        df = pd.concat([df1, df2])
        df = df[df['proposal_id'] == self.onchain_proposal_id]

        self.onc_votes = df

    def calculate_basic_tally(self):
        
        assert self.proposal_type_label == 'basic', f"Proposal type is not basic: {self.proposal_type_label}"

        def bigint_sum(arr):
            return str(sum([int(o) for o in arr.values]))
    
        counts = self.onc_votes.groupby('support')['weight'].apply(bigint_sum).to_dict()
        against_votes = int(counts.get(0, 0))
        for_votes = int(counts.get(1, 0))
        abstain_votes = int(counts.get(2, 0))

        approval_thresh_pct = (self.proposal_type_info['approval_threshold_bps'] / 10000)
        quorum_thresh_pct = (self.proposal_type_info['quorum_bps'] / 10000)
        
        votable_supply = self.votable_supply   
        assert quorum_thresh_pct == self.quorum / votable_supply

        return StandardTally(votable_supply, quorum_thresh_pct, approval_thresh_pct, against_votes, for_votes, abstain_votes, include_abstain=self.include_abstain)

    def calculate_approval_tally(self):
        
        assert self.proposal_type_label == 'approval', f"Proposal type is not approval: {self.proposal_type_label}"

        onc_votes = self.onc_votes.copy()

        def params_decode(arr):
            try:
                return decode_abi(["uint256[]"], bytes.fromhex(arr))[0]
            except TypeError as e:
                return [-1]

        onc_votes['params'] = onc_votes['params'].apply(params_decode)

        def bigint_sum(arr):
            return str(sum([int(o) for o in arr.values]))

        ballot_feed = onc_votes[['support', 'weight', 'params']].explode('params')

        counts = ballot_feed.groupby(['params', 'support']).apply(bigint_sum)
        totals = ballot_feed.groupby(['params'])['weight'].apply(bigint_sum).to_dict()
    
        total_voting_vp = onc_votes[['support', 'weight']].groupby('support').apply(bigint_sum).to_dict()

        final_dict = defaultdict(dict)
        for (param, support), value in counts.items():
            final_dict[param][support] = value
        counts = dict(final_dict)

        """
        At this point we have "counts" of the form...

        {-1: {2: '6515768095338571250010090'},
        0: {0: '48664653865959285301', 1: '31431910661813432620160489'},
        1: {1: '35035962495117270703561571'},
        2: {0: '48664653865959285301', 1: '17033284171118898054256072'},
        3: {1: '17663853612321229474897508'},
        4: {0: '48664653865959285301', 1: '24934837283900123569914475'},
        5: {1: '28476520065880757383430022'},
        6: {0: '48664653865959285301', 1: '23272354186448414025424072'},
        7: {1: '21779420495943287974126505'}}

        and "total" is of the form...  ...but unclear if we really need these.

        {-1: '6515768095338571250010090', 0: '31431959326467298579445790', 1: '35035962495117270703561571', 2: '17033332835772764013541373', 3: '17663853612321229474897508', 4: '24934885948553989529199776', 5: '28476520065880757383430022', 6: '23272402851102279984709373', 7: '21779420495943287974126505'}

        and "total voting vp" is of the form...

        {0: '48664653865959285301', 1: '40422986148598663804350243', 2: '6515768095338571250010090'}

        """

        approval_thresh_pct = (self.proposal_type_info['approval_threshold_bps'] / 10000)
        quorum_thresh_pct = (self.proposal_type_info['quorum_bps'] / 10000)
        
        votable_supply = self.votable_supply   
        assert quorum_thresh_pct == self.quorum / votable_supply

        # TODO - should this really be "include_abstain=True"?
        return ApprovalTally(votable_supply, quorum_thresh_pct, approval_thresh_pct, counts, total_voting_vp, include_abstain=True)

    def show_result(self):

        weights = [1]

        print()
        print(self)
        print()

        if self.proposal_type_label == 'basic':
            tally = self.calculate_basic_tally()

            print(tally.gen_tally_report("Token House"))
            
            final_tally = FinalTally([tally], weights = weights, quorum_thresh_pct = tally.quorum_thresh_pct, approval_thresh_pct = tally.approval_thresh_pct)
            print(final_tally.gen_tally_report("Final"))

        elif self.proposal_type_label == 'approval':
            tally = self.calculate_approval_tally()

            print(tally.gen_tally_report("Token House"))
        else:
            raise Exception(f"Unknown proposal type: {self.proposal_type_label}")


class Hybrid(Proposal):
    emoji = '☯️'

    def __init__(self, off_chain, on_chain):
        self.off_chain_p = OffChain(off_chain)
        self.off_chain = off_chain.to_dict()

        self.on_chain_p = OnChain(on_chain)
        self.on_chain = on_chain.to_dict()

        assert self.off_chain_p.include_abstain == self.on_chain_p.include_abstain
        self.include_abstain = self.off_chain_p.include_abstain

        self.onchain_proposal_id = self.on_chain_p.id
        self.offchain_proposal_id = self.off_chain_p.id

        self.proposal_type_id = self.on_chain['proposal_type']
        self.proposal_type_info = self.on_chain_p.proposal_type_info
        
        self.row = deepcopy(self.on_chain)
        self.row.update(self.off_chain)

        self.id = f"{self.on_chain['proposal_id']}-{self.off_chain['proposalId']}"

    def show_result(self):

        weights = [1/2, 1/6, 1/6, 1/6]

        print()
        print(self)
        print()

        if self.proposal_type_label == 'basic':
            onc_tally = self.on_chain_p.calculate_basic_tally()
            offc_tallies = self.off_chain_p.calculate_standard_tallies()

        elif self.proposal_type_label == 'approval':
            onc_tally = self.on_chain_p.calculate_approval_tally()
            offc_tallies = self.off_chain_p.calculate_approval_tallies()

        tallies = [onc_tally] + offc_tallies

        print(tallies[0].gen_tally_report("Token House", weights[0]))
        print(tallies[1].gen_tally_report("Citizen House - Apps", weights[1]))
        print(tallies[2].gen_tally_report("Citizen House - Users", weights[2]))
        print(tallies[3].gen_tally_report("Citizen House - Chains", weights[3]))

        quorum_thresh_pct = tallies[0].quorum_thresh_pct
        approval_thresh_pct = tallies[0].approval_thresh_pct

        for i, t in enumerate(tallies):
            assert t.quorum_thresh_pct == quorum_thresh_pct, f"Quorum PCTs do not match: {t.quorum_thresh_pct} != {quorum_thresh_pct} for tally {i}"
            assert t.approval_thresh_pct == approval_thresh_pct, f"Approval Threshold PCTs do not match: {t.approval_thresh_pct} != {approval_thresh_pct} for tally {i}"

        final_tally = FinalTally(tallies, weights = weights, quorum_thresh_pct = quorum_thresh_pct, approval_thresh_pct = approval_thresh_pct, include_abstain=self.include_abstain)
        print(final_tally.gen_tally_report("Final"))
    
    def load_context(self):

        self.off_chain_p.load_context()
        self.on_chain_p.load_context()

class ProposalLister:
    def __init__(self, on_chain_props_df, off_chain_props_df):

        off_chain = []
        on_chain = []
        hybrid = []

        for idx, row in off_chain_props_df.iterrows():
            if row['onchain_proposalid'] == '0':
                off_chain.append(OffChain(row))
            else:
                on_chain_prop = on_chain_props_df[on_chain_props_df['proposal_id'] == row['onchain_proposalid']]
                hybrid.append(Hybrid(row, on_chain_prop.iloc[0]))
                on_chain_props_df = on_chain_props_df[on_chain_props_df['proposal_id'] != row['onchain_proposalid']]

        for idx, row in on_chain_props_df.iterrows():
            on_chain.append(OnChain(row))

        self.off_chain = off_chain
        self.on_chain = on_chain
        self.hybrid = hybrid

    @staticmethod
    def load():

        df_onc, df_off = load_proposal_data()
        
        prop_lister = ProposalLister(df_onc, df_off)
        return prop_lister

    
    def get_proposal(self, proposal_id):
        for prop in self.off_chain:
            if prop.id == proposal_id:
                return prop
        for prop in self.on_chain:
            if prop.id == proposal_id:
                return prop
        for prop in self.hybrid:
            if prop.id == proposal_id:
                return prop
        raise Exception(f"Proposal {proposal_id} not found")

    def list_proposals(self):
        
        print(f"\nOff-chain proposals: {len(self.off_chain)}")

        for oncp in self.off_chain:
            print(oncp)
        
        print(f"\nOn-chain proposals: {len(self.on_chain)}")

        for oncp in self.on_chain:   
            print(oncp)

        print(f"\nHybrid proposals: {len(self.hybrid)}")

        for hybrid_prop in self.hybrid:
            print(hybrid_prop)

        return self

def load_proposal_data():

    try:    
        df_onc1 = pd.read_csv(DATA_DIR / DEPLOYMENT / (PROPOSAL_CREATED_2 + '.csv'))
    except FileNotFoundError:
        df_onc1 = pd.DataFrame()
    
    try:    
        df_onc2 = pd.read_csv(DATA_DIR / DEPLOYMENT / (PROPOSAL_CREATED_4 + '.csv'))
    except FileNotFoundError:
        df_onc2 = pd.DataFrame()
    
    df_onc = pd.concat([df_onc1, df_onc2])

    try:    
        df_off = pd.read_csv(DATA_DIR / DEPLOYMENT / "CreateProposal.csv").drop_duplicates(['id'], keep='last')
    except FileNotFoundError:
        df_off = pd.DataFrame()

    return df_onc, df_off

if __name__ == '__main__':
    cli()
