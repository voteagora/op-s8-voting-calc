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

def bte(x):
    return "✅" if x else "❌"


class BasicTally:

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


class FinalBasicTally:
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


class OffChainBasicMixin:

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

class OnChainBasicMixin:

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

        return BasicTally(votable_supply, quorum_thresh_pct, approval_thresh_pct, against_votes, for_votes, abstain_votes, include_abstain=self.include_abstain)

