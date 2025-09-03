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


class OptimisticTally:

    def __init__(self, eligible_votes, against_thresh_pct, against_votes=0, abstain_votes=0, include_abstain=False, tiers=False):
        """
        eligible_votes: Number of eligible voters (for off-chain) or Votable Supply (for on-chain)
        
        against_thresh_pct: Against threshold percentage as a float.  Eg. 0.5 for 50%

        against_votes: Number of against votes (for off-chain) or VP against (for on-chain)
        abstain_votes: Number of abstain votes (for off-chain) or VP abstain (for on-chain)
        """

        self.tiers = tiers

        self.against_votes = against_votes
        self.abstain_votes = abstain_votes

        self.include_abstain = include_abstain

        if self.include_abstain:
            self.total_votes = against_votes + abstain_votes
        else:
            self.total_votes = against_votes
    
        self.eligible_votes = eligible_votes

        self.against_thresh_pct = against_thresh_pct

        if self.total_votes != 0:

            assert self.eligible_votes != 0, "eligible_votes must be non-zero, there should be no reason it's not."

            self.relative_against_pct = self.against_votes / self.total_votes
            self.relative_abstain_pct = self.abstain_votes / self.total_votes

            self.absolute_against_pct = self.against_votes / self.eligible_votes
            self.absolute_abstain_pct = self.abstain_votes / self.eligible_votes

            self.against = self.against_votes / self.total_votes
            self.passing_against_threshold = self.against >= self.against_thresh_pct

        else:
            self.relative_against_pct = 0
            self.relative_abstain_pct = 0
            self.absolute_against_pct = 0
            self.absolute_abstain_pct = 0
            self.quorum = 0
            self.against = 0

            # self.passing_quorum = self.quorum >= self.quorum_thresh_pct
            self.passing_against_threshold = self.against >= self.against_thresh_pct

    def gen_tally_report(self, label, weight=1, include_quorum=True):

        
        tally = f"{label} Tally"
        
        if weight < 1 and not self.tiers:
            tally += f" [{weight:.2%} of Final]\n"
        else:
            tally += "\n"

        tally += "-" * (len(tally) - 1) + "\n"


        tally += f"Total:    {self.total_votes:>32}\n"
        tally += f"Eligible: {self.eligible_votes:>32}\n"

        tally += f"Against:  {self.against_votes:>32} ({self.relative_against_pct:.1%} of total | {self.absolute_against_pct:.1%} of eligible)\n"

        if self.include_abstain:
            tally += f"Abstain:  {self.abstain_votes:>32} ({self.relative_abstain_pct:.1%} of total | {self.absolute_abstain_pct:.1%} of eligible)\n"

        if self.tiers:
            lowest_thresh = []
            for group_cnt, thresh in self.tiers.items():
                if self.against >= thresh:
                    lowest_thresh.append(thresh)

            tally += f"Against: {self.against:.2%}"
            
            if len(lowest_thresh) >0:
                tally += f" (>= {min(lowest_thresh):.2%}-threshold tripped) \n"
            else:
                tally += f" (ie, did not clear lowest threshold.)\n"
        else:
            tally += f"Against (Outcome): {self.against:.2%} {bte(self.passing_against_threshold)} ({self.against_thresh_pct:.0%})\n"

        if not self.passing_against_threshold:
            tally += "✅ PASSING\n"
        else:
            tally += "❌ VETOED\n"

        return tally


class FinalOptimisticTally:
    def __init__(self, tallies, weights, against_thresh_tiers, include_abstain=False):
        self.tallies = tallies
        self.weights = weights
        self.against_thresh_tiers = against_thresh_tiers

        self.tiered = len(self.against_thresh_tiers) > 1

        # Is this stuff all irrelevant?
        self.include_abstain = include_abstain
        self.relative_against_pct = sum([t.relative_against_pct * w for t, w in zip(tallies, weights)])
        self.relative_abstain_pct = sum([t.relative_abstain_pct * w for t, w in zip(tallies, weights)])

        self.absolute_against_pct = sum([t.absolute_against_pct * w for t, w in zip(tallies, weights)])
        self.absolute_abstain_pct = sum([t.absolute_abstain_pct * w for t, w in zip(tallies, weights)])

        self.against = sum([t.against * w for t, w in zip(tallies, weights)])
        self.include_abstain = include_abstain

        against_thresh_tiers = {k: against_thresh_tiers[k] for k in sorted(against_thresh_tiers)}

        for tier_cnt, against_thresh_pct in against_thresh_tiers.items():

            self.against_thresh_pct = against_thresh_pct
    
            self.passing_against_threshold_cnt = sum([t.against >= against_thresh_pct for t in tallies])
            self.passing_against_threshold =  self.passing_against_threshold_cnt >= tier_cnt

            if self.passing_against_threshold:
                break



    def gen_tally_report(self, label):

        passing = not self.passing_against_threshold

        tally = f"{label} Tally\n"
        tally += "-" * (len(tally) - 1) + "\n"

        if self.tiered:

            tally += "Given...\n"
            for group_cnt, threshold in self.against_thresh_tiers.items():
                tally += f">={threshold}% veto across {group_cnt} groups.\n"

            tally += f"Given relevant against-threshold is {self.against_thresh_pct}, and {self.passing_against_threshold_cnt} cleared that level, so this proposal is...\n"

        else:
            tally += f"Against: ({self.relative_against_pct:.1%} of total | {self.absolute_against_pct:.1%} of eligible)\n"

            if self.include_abstain:
                tally += f"Abstain: ({self.relative_abstain_pct:.1%} of total | {self.absolute_abstain_pct:.1%} of eligible)\n"

            tally += f"Against (Outcome): {self.against:.2%} {bte(self.passing_against_threshold)} ({self.against_thresh_pct:.0%})\n"


        if passing:
            tally += "✅ PASSING\n"
        else:
            tally += "❌ DEFEATED\n"

        return tally


class OffChainOptimisticMixin:

    def calculate_optimistic_tallies(self):
        
        assert self.proposal_type_label == 'optimistic', f"Proposal type is not optimistic: {self.proposal_type_label}"

        tiers = self.proposal_type_info['tiers']

        def bigint_sum(arr):
            return str(sum([int(o) for o in arr.values]))

        counts = self.offc_votes.groupby(['SelectionMethod', 'support'])['weight'].sum()
        
        empty = pd.Series(dtype='int64', name='weight')
        empty.index.name = 'support'

        tallies = []

        for category in ['app', 'user', 'chain']:
            cat_counts = counts.get(category, empty).to_dict(into=defaultdict(int))

            against_thresh_pct = 0.125 # Hardcoded? TODO - make match. 

            eligible_votes = self.ch_counts[category]

            tally = OptimisticTally(eligible_votes, against_thresh_pct, cat_counts[0], cat_counts[2], include_abstain=self.include_abstain, tiers=tiers)
            tallies.append(tally)
        
        return tallies

class OnChainOptimisticMixin:

    def calculate_optimistic_tally(self, tiers=False):

        assert self.proposal_type_label == 'optimistic', f"Proposal type is not optimistic: {self.proposal_type_label}"

        def bigint_sum(arr):
            return str(sum([int(o) for o in arr.values]))
    
        counts = self.onc_votes.groupby('support')['weight'].apply(bigint_sum).to_dict()
        against_votes = int(counts.get(0, 0))
        abstain_votes = int(counts.get(2, 0))

        against_thresh_pct = 0.125 # Hardcoded? TODO - figure out how this is set for on-chain.
        
        votable_supply = self.votable_supply   
        
        return OptimisticTally(votable_supply, against_thresh_pct, against_votes, abstain_votes, include_abstain=self.include_abstain, tiers=tiers)

