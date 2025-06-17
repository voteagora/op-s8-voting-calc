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
from .calc_basic import OffChainBasicMixin, OnChainBasicMixin,                     BasicTally,    FinalBasicTally
from .calc_approval import OffChainApprovalMixin, OnChainApprovalMixin, Choice, ApprovalTally, FinalApprovalTally

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

    @property
    def choice_list(self):
        assert self.proposal_type_label == 'approval', f"Proposal type is not approval: {self.proposal_type_label}" 

        if 'choices' in self.row:
            choice_list = self.row['choices'][2:-2].split("', '")
            return choice_list
        else:
            return [c[4] for c in self.decoded_proposal_data_choices]
        
    def __str__(self):
        return f"{self.emoji} {self.proposal_type_label.upper()}: {self.id}, title={self.title}"

    def load_meta(self):

        self.gov_address = onchain_config['gov']['address']
        self.ptc_address = onchain_config['ptc']['address']

        fname = DATA_DIR / DEPLOYMENT / (self.id + '.json')
        onchain_meta = json.load(open(fname, 'r'))
        self.proposal_type_info = onchain_meta['proposal_type_info']
        self.quorum = onchain_meta['quorum']
        self.votable_supply = onchain_meta['votable_supply']
        self.asof_block_num = onchain_meta['asof_block_num']
        self.proposal_type_id = onchain_meta['proposal_type_id']
        self.counting_mode = onchain_meta['counting_mode']


class OffChain(Proposal, OffChainBasicMixin, OffChainApprovalMixin):
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

        if self.proposal_type_label == 'approval':
            self.max_approvals = self.row['max_approvals']
            
            if self.row['criteria'] == 0:
                # In Seasion 8, this is in basis points.  Before S8, this number was in units of tokens.
                self.criteria = 'minimum_threshold'
                self.choice_approval_threshold_pct = self.row['criteria_value'] / 10000
                assert self.choice_approval_threshold_pct <= 1.0, f"Invalid choice approval threshold: {self.choice_approval_threshold_pct}"
            else:
                self.criteria = 'top_choices'
                self.number_of_winners = self.row['criteria_value']
                raise Exception("Criteria 1 not implemented")
            
            self.criteria_value = self.row['criteria_value']



    def load_context(self):

        # Assumed hard-coded for now.
        self.ch_counts = {'app' : 100, 'user': 1000, 'chain' : 15}

        citizens = pd.read_csv(DATA_DIR / DEPLOYMENT / "Citizens.csv")

        # Filter out non-compliant attestations.
        citizens = citizens[citizens['SelectionMethod'].isin(['5.1', '5.2', '5.3'])]
        citizens['SelectionMethod'] = citizens['SelectionMethod'].map({'5.1': 'chain', '5.2': 'app', '5.3': 'user'})
 
        df = pd.read_csv(DATA_DIR / DEPLOYMENT / 'Vote.csv')

        offc_votes = df[df['proposalId'] == self.offchain_proposal_id].copy()

        if self.proposal_type_label == 'basic':
            offc_votes['support'] = offc_votes['params'].apply(lambda x: json.loads(x)[0])
            offc_votes['weight'] = 1
            cols = ['SelectionMethod', 'support', 'weight']
        elif self.proposal_type_label == 'approval':
            offc_votes['choices'] = offc_votes['params'].apply(lambda x: json.loads(x))
            offc_votes['weight'] = 1
            cols = ['SelectionMethod', 'choices', 'weight']

        offc_votes = offc_votes[offc_votes['refUID'].isin(citizens[~citizens['revoked']]['id'])].copy()

        if offc_votes.duplicated(subset=['refUID']).any():
            raise ValueError("Duplicates found in offc_votes.refUID.")

        if citizens.duplicated(subset=['id']).any():
            raise ValueError("Duplicates found in citizens.id.")

        offc_votes_with_citizens = offc_votes.merge(citizens, left_on='refUID', right_on='id', how='inner', validate='one_to_one')

        offc_votes_with_citizens = offc_votes_with_citizens[cols].copy()

        self.offc_votes = offc_votes_with_citizens        

    def calculate_basic_tallies(self):
        
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
            
            tally = BasicTally(eligible_votes, quorum_thresh_pct, approval_thresh_pct, cat_counts[0], cat_counts[1], cat_counts[2], include_abstain=self.include_abstain)
            tallies.append(tally)
        
        return tallies

    def show_result(self):

        weights = [1/3, 1/3, 1/3]

        print()
        print(self)
        print()

        tallies = self.calculate_basic_tallies()

        print(tallies[0].gen_tally_report("Citizen House - Apps", weights[0]))
        print(tallies[1].gen_tally_report("Citizen House - Users", weights[1]))
        print(tallies[2].gen_tally_report("Citizen House - Chains", weights[2]))

        quorum_thresh_pct = tallies[0].quorum_thresh_pct
        approval_thresh_pct = tallies[0].approval_thresh_pct

        for i, t in enumerate(tallies):
            assert t.quorum_thresh_pct == quorum_thresh_pct, f"Quorum PCTs do not match: {t.quorum_thresh_pct} != {quorum_thresh_pct} for tally {i}"
            assert t.approval_thresh_pct == approval_thresh_pct, f"Approval Threshold PCTs do not match: {t.approval_thresh_pct} != {approval_thresh_pct} for tally {i}"

        final_tally = FinalBasicTally(tallies, weights = weights, quorum_thresh_pct = quorum_thresh_pct, approval_thresh_pct = approval_thresh_pct, include_abstain=self.include_abstain)
        print(final_tally.gen_tally_report("Final"))

from .decode_creates import decode_proposal_data

class OnChain(Proposal, OnChainBasicMixin, OnChainApprovalMixin):
    emoji = '⛓️'
    def __init__(self, row):
        self.row = row.to_dict()
        self.id = self.row['proposal_id']
        self.onchain_proposal_id = self.id

        self.load_meta()

        self.include_abstain = 'abstain' in self.counting_mode

        proposal_data = self.row.get('proposal_data', pd.NA)

        if pd.isna(proposal_data):
            proposal_data = ''

        if proposal_data:
            self.decoded_proposal_data = decode_proposal_data(self.proposal_type_label, proposal_data)
            
            if self.proposal_type_label == 'basic':
                self.decoded_proposal_data_choices, self.decoded_proposal_data_settings = None, None
            elif self.proposal_type_label == 'approval':
                self.decoded_proposal_data_choices, self.decoded_proposal_data_settings = self.decoded_proposal_data
            elif self.proposal_type_label == 'optimistic':
                self.decoded_proposal_data_choices, self.decoded_proposal_data_settings = None, self.decoded_proposal_data[0]
        else:
            self.decoded_proposal_data = None
            self.decoded_proposal_data_choices, self.decoded_proposal_data_settings = None, None


    def load_context(self):

        df1 = pd.read_csv(DATA_DIR / DEPLOYMENT / 'VoteCast(address,uint256,uint8,uint256,string).csv')
        df2 = pd.read_csv(DATA_DIR / DEPLOYMENT / 'VoteCastWithParams(address,uint256,uint8,uint256,string,bytes).csv')
        df = pd.concat([df1, df2])
        df = df[df['proposal_id'] == self.onchain_proposal_id]

        self.onc_votes = df

    def show_result(self):

        weights = [1]

        print()
        print(self)
        print()

        if self.proposal_type_label == 'basic':
            tally = self.calculate_basic_tally()
            print(tally.gen_tally_report("Token House"))
            
            final_tally = FinalBasicTally([tally], weights = weights, quorum_thresh_pct = tally.quorum_thresh_pct, approval_thresh_pct = tally.approval_thresh_pct)
            print(final_tally.gen_tally_report("Final"))

        elif self.proposal_type_label == 'approval':
            tally = self.calculate_approval_tally()
            print(tally.gen_tally_report("Token House", include_quorum=False))

            final_tally = FinalApprovalTally([tally], weights = weights, quorum_thresh_pct = tally.quorum_thresh_pct, approval_thresh_pct = tally.approval_thresh_pct)
            print(final_tally.gen_tally_report("Final"))
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

        # self.decoded_proposal_data = self.on_chain_p.decoded_proposal_data
        # self.decoded_proposal_data_choices, self.decoded_proposal_data_settings = self.on_chain_p.decoded_proposal_data_choices, self.on_chain_p.decoded_proposal_data_settings

        # TODO - This is a hack, to transfer on-chain context into the off-chain proposal object before any calcs.
        # self.off_chain_p.decoded_proposal_data = self.decoded_proposal_data
        # self.off_chain_p.decoded_proposal_data_choices, self.off_chain_p.decoded_proposal_data_settings = self.decoded_proposal_data_choices, self.decoded_proposal_data_settings

        self.id = f"{self.on_chain['proposal_id']}-{self.off_chain['proposalId']}"

    def show_result(self):

        weights = [1/2, 1/6, 1/6, 1/6]

        print()
        print(self)
        print()

        if self.proposal_type_label == 'basic':
            onc_tally = self.on_chain_p.calculate_basic_tally()
            offc_tallies = self.off_chain_p.calculate_basic_tallies()

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

        if self.proposal_type_label == 'basic':
            final_tally = FinalBasicTally(tallies, weights = weights, quorum_thresh_pct = quorum_thresh_pct, approval_thresh_pct = approval_thresh_pct, include_abstain=self.include_abstain)
            print(final_tally.gen_tally_report("Final"))
        elif self.proposal_type_label == 'approval':
            final_tally = FinalApprovalTally(tallies, weights = weights, quorum_thresh_pct = quorum_thresh_pct, approval_thresh_pct = approval_thresh_pct)
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
