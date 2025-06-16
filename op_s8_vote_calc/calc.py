import click
import csv
from pathlib import Path
from yaml import load, FullLoader
from pprint import pprint
import json
from copy import deepcopy

from .jsonrpc_client import JsonRpcHistHttpClient
from .graphqleas_client import EASGraphQLClient
from .utils import load_config
from web3 import Web3
from collections import defaultdict

from eth_abi import decode

from abifsm import ABISet, ABI
from .utils import camel_to_snake
from .signatures import *

from .attestations import meta as all_meta

import pandas as pd

DATA_DIR = Path('op_s8_vote_calc/data')
    

class Proposal:

    @property
    def title(self):
        description = self.row.get('description', None)
        return description.split("\n")[0]

    @property
    def proposal_type_label(self):
        return self.proposal_type_info['friendly_name']

    def __str__(self):
        return f"{self.emoji} {self.proposal_type_label}: id={self.id}, title={self.title}"

    def get_quorum(self, w3, gov_address):

        contract_abi = [
            {
                "constant": True,
                "inputs": [{"name": "proposal_id", "type": "uint256"}],
                "name": "quorum",
                "outputs": [{"name": "", "type": "uint256"}],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            }
        ]

        # Create a contract instance
        contract = w3.eth.contract(address=gov_address, abi=contract_abi)
        return contract.functions.quorum(int(self.onchain_proposal_id)).call()
    
    def get_votable_supply(self, w3, gov_address):

        contract_abi = [
            {
                "constant": True,
                "inputs": [{"name": "proposal_id", "type": "uint256"}],
                "name": "proposalSnapshot",
                "outputs": [{"name": "", "type": "uint256"}],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            }
        ]

        # Create a contract instance
        contract = w3.eth.contract(address=gov_address, abi=contract_abi)

        self.start_block_number = contract.functions.proposalSnapshot(int(self.onchain_proposal_id)).call()

        contract_abi = [
            {
                "constant": True,
                "inputs": [{"name": "block_number", "type": "uint256"}],
                "name": "votableSupply",
                "outputs": [{"name": "", "type": "uint256"}],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            }
        ]

        # Create a contract instance
        contract = w3.eth.contract(address=gov_address, abi=contract_abi)

        return contract.functions.votableSupply(int(self.start_block_number)).call()

    def load_onchain_context(self, env, w3, gov_address):

        self.quorum = self.get_quorum(w3, gov_address)
        self.votable_supply = self.get_votable_supply(w3, gov_address)

        config, _ = load_config(env)

        df1 = pd.read_csv(DATA_DIR / env / 'VoteCast(address,uint256,uint8,uint256,string).csv')
        df2 = pd.read_csv(DATA_DIR / env / 'VoteCastWithParams(address,uint256,uint8,uint256,string,bytes).csv')
        df = pd.concat([df1, df2])
        df = df[df['proposal_id'] == self.onchain_proposal_id]

        self.onc_votes = df


    def load_offchain_context(self, env):

        # Assumed hard-coded for now.
        self.ch_counts = {'apps' : 100, 'users': 10000, 'chains' : 15}

        citizens = pd.read_csv(DATA_DIR / env / "Citizens.csv")

        # Filter out non-compliant attestations.
        citizens = citizens[citizens['SelectionMethod'].isin(['5.1', '5.2', '5.3'])]
        citizens['SelectionMethod'] = citizens['SelectionMethod'].map({'5.1': 'apps', '5.2': 'users', '5.3': 'chains'})
 
        df = pd.read_csv(DATA_DIR / env / 'Vote.csv')

        self.offc_votes = df[df['proposalId'] == self.offchain_proposal_id]
        self.offc_votes['support'] = self.offc_votes['params'].apply(lambda x: json.loads(x)[0])
        self.offc_votes['weight'] = 1

        self.offc_votes = self.offc_votes[['attester', 'support', 'weight']]

        self.offc_votes = self.offc_votes.merge(citizens, on='attester')



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

    def print_tally(self, label, weight):

        tally = f"{label} Tally"
        
        if weight < 1:
            tally += f" [{weight:.2%} of Final]\n"
        else:
            tally += "\n"

        tally += "-" * (len(tally) - 1) + "\n"


        tally += f"Given {self.total_votes} total votes, and {self.eligible_votes} eligible votes... \n"

        tally += f"For: {self.for_votes} ({self.relative_for_pct:.1%} of total | {self.absolute_for_pct:.1%} of eligible)\n"
        tally += f"Against: {self.against_votes} ({self.relative_against_pct:.1%} of total | {self.absolute_against_pct:.1%} of eligible)\n"

        if self.include_abstain:
            tally += f"Abstain: {self.abstain_votes} ({self.relative_abstain_pct:.1%} of total | {self.absolute_abstain_pct:.1%} of eligible)\n"

        tally += f"Quorum: {self.quorum:.2%} {bte(self.passing_quorum)} ({self.quorum_thresh_pct:.0%}), Approval: {self.approval:.2%} {bte(self.passing_approval_threshold)} ({self.approval_thresh_pct:.0%}) -> "

        if self.passing_quorum and self.passing_approval_threshold:
            tally += "✅ PASSING\n"
        else:
            tally += "❌ DEFEATED\n"

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


    def print_tally(self, label):

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
    def __init__(self, row, proposal_label_map):
        self.row = row.to_dict()
        self.offchain_proposal_id = self.row['id']
        self.id = self.offchain_proposal_id
        self.proposal_type_id = self.row['proposal_type_id']
        self.proposal_type_info = deepcopy( proposal_label_map[str(self.proposal_type_id)])
        self.proposal_type_info['friendly_name'] = self.row['proposal_type']
        if 'tiers' in self.row:
            self.proposal_type_info['tiers'] = self.row['tiers']

    def show_result(self):

        print(self)

        tallies = self.calculate_standard_tally()

        for tally in tallies:
            print(tally)
        
        final_tally = FinalTally(tallies, weights = [1/3, 1/3, 1/3])
        print(final_tally)

    def calculate_standard_tally(self):
        
        assert self.proposal_type_label == 'STANDARD'

        def bigint_sum(arr):
            return str(sum([int(o) for o in arr.values]))

        counts = self.offc_votes.groupby(['SelectionMethod', 'support'])['weight'].sum()
        
        empty = pd.Series(dtype='int64', name='weight')
        empty.index.name = 'support'

        tallies = []

        for category in ['apps', 'users', 'chains']:
            cat_counts = counts.get(category, empty).to_dict(into=defaultdict(int))

            approval_thresh_pct = (self.proposal_type_info['approval_thresh'] / 10000)
            quorum_thresh_pct =  (self.proposal_type_info['quorum'] / 10000)

            eligible_votes = self.ch_counts[category]
            
            tally = StandardTally(eligible_votes, quorum_thresh_pct, approval_thresh_pct, cat_counts[0], cat_counts[1], cat_counts[2], include_abstain=False)
            tallies.append(tally)
        
        return tallies

class OnChain(Proposal):
    emoji = '⛓️'
    def __init__(self, row, proposal_label_map):
        self.row = row.to_dict()
        self.id = self.row['proposal_id']
        self.onchain_proposal_id = self.id

        self.proposal_type_id = self.row['proposal_type']
        self.proposal_type_info = deepcopy(proposal_label_map[str(self.proposal_type_id)])

    def calculate_standard_tally(self):
        
        assert self.proposal_type_label == 'STANDARD'

        def bigint_sum(arr):
            return str(sum([int(o) for o in arr.values]))
    
        counts = self.onc_votes.groupby('support')['weight'].apply(bigint_sum).to_dict()
        against_votes = int(counts.get(0, 0))
        for_votes = int(counts.get(1, 0))
        abstain_votes = int(counts.get(2, 0))

        approval_thresh_pct = (self.proposal_type_info['approval_thresh'] / 10000)
        quorum_thresh_pct = (self.proposal_type_info['quorum'] / 10000)
        
        votable_supply = self.votable_supply   
        assert quorum_thresh_pct == self.quorum / votable_supply

        return [StandardTally(votable_supply, quorum_thresh_pct, approval_thresh_pct, against_votes, for_votes, abstain_votes, include_abstain=False)]

    def show_result(self):

        print(self)

        tallies = self.calculate_standard_tally()

        for tally in tallies:
            print(tally)
        
        final_tally = FinalTally(tallies, weights = [100])
        print(final_tally)


class Hybrid(Proposal):
    emoji = '☯️'

    def __init__(self, off_chain, on_chain, proposal_label_map):
        self.off_chain_p = OffChain(off_chain, proposal_label_map)
        self.off_chain = off_chain.to_dict()

        self.on_chain_p = OnChain(on_chain, proposal_label_map)
        self.on_chain = on_chain.to_dict()
        
        self.onchain_proposal_id = self.on_chain_p.id
        self.offchain_proposal_id = self.off_chain_p.id

        self.proposal_type_id = self.on_chain['proposal_type']
        self.proposal_type_info = deepcopy(proposal_label_map[str(self.proposal_type_id)])
        
        self.row = deepcopy(self.on_chain)
        self.row.update(self.off_chain)

        self.id = f"{self.on_chain['proposal_id']}-{self.off_chain['id']}"

    def show_result(self):

        weights = [1/2, 1/6, 1/6, 1/6]

        print()
        print(self)
        print()

        onc_tallies = self.on_chain_p.calculate_standard_tally()
        offc_tallies = self.off_chain_p.calculate_standard_tally()

        tallies = onc_tallies + offc_tallies

        print(tallies[0].print_tally("Token House", weights[0]))
        print(tallies[1].print_tally("Citizen House - Apps", weights[1]))
        print(tallies[2].print_tally("Citizen House - Users", weights[2]))
        print(tallies[3].print_tally("Citizen House - Chains", weights[3]))

        quorum_thresh_pct = tallies[0].quorum_thresh_pct
        approval_thresh_pct = tallies[0].approval_thresh_pct

        for i, t in enumerate(tallies):
            assert t.quorum_thresh_pct == quorum_thresh_pct, f"Quorum PCTs do not match: {t.quorum_thresh_pct} != {quorum_thresh_pct} for tally {i}"
            assert t.approval_thresh_pct == approval_thresh_pct, f"Approval Threshold PCTs do not match: {t.approval_thresh_pct} != {approval_thresh_pct} for tally {i}"

        final_tally = FinalTally(tallies, weights = weights, quorum_thresh_pct = quorum_thresh_pct, approval_thresh_pct = approval_thresh_pct)
        print(final_tally.print_tally("Final"))
    
    def load_offchain_context(self, env):

        self.off_chain_p.load_offchain_context(env)
    
    def load_onchain_context(self, env, w3, gov_address):

        self.on_chain_p.load_onchain_context(env, w3, gov_address)

class ProposalLister:
    def __init__(self, on_chain_props_df, off_chain_props_df, prop_type_map):

        off_chain = []
        on_chain = []
        hybrid = []

        for idx, row in off_chain_props_df.iterrows():
            
            if row['onchain_proposalid'] == '0':
                off_chain.append(OffChain(row, prop_type_map))
            else:
                on_chain_prop = on_chain_props_df[on_chain_props_df['proposal_id'] == row['onchain_proposalid']]
                hybrid.append(Hybrid(row, on_chain_prop.iloc[0], prop_type_map))
                on_chain_props_df = on_chain_props_df[on_chain_props_df['proposal_id'] != row['onchain_proposalid']]

        for idx, row in on_chain_props_df.iterrows():
            on_chain.append(OnChain(row, prop_type_map))

        self.off_chain = off_chain
        self.on_chain = on_chain
        self.hybrid = hybrid

    @staticmethod
    def load(env):

        config, _ = load_config(env)
        prop_type_map = config['ptc']['proposal_label_map']
        df_onc, df_off = load_proposal_data(env)
        prop_lister = ProposalLister(df_onc, df_off, prop_type_map)
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

def load_proposal_data(env):

    df_onc1 = pd.read_csv(DATA_DIR / env / (PROPOSAL_CREATED_2 + '.csv'))
    df_onc2 = pd.read_csv(DATA_DIR / env / (PROPOSAL_CREATED_4 + '.csv'))
    df_onc = pd.concat([df_onc1, df_onc2])

    df_off = pd.read_csv(DATA_DIR / env / "CreateProposal.csv").drop_duplicates(['id'], keep='last')

    return df_onc, df_off

if __name__ == '__main__':
    cli()
