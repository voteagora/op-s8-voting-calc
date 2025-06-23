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
from .calc_basic import BasicTally
from .signatures import *

from .attestations import meta as all_meta

import pandas as pd
import numpy as np

DATA_DIR = Path(os.getenv('S8_DATA_DIR', 'op_s8_vote_calc/data'))
DEPLOYMENT = os.getenv('S8_DEPLOYMENT', 'test')

onchain_config, offchain_config = load_config()
PTC_MODULES = {v['address'] : v['name'] for v in onchain_config['gov']['modules']}

def bte(x):
    return "✅" if x else "❌"

class Choice(BasicTally):

    def __init__(self, label, eligible_votes, quorum_thresh_pct, approval_thresh_pct, votes, include_abstain=False):

        self.label = label

        against_votes = int(votes.get(0, 0))
        for_votes = int(votes.get(1, 0))
        abstain_votes = int(votes.get(2, 0)) if include_abstain else 0

        super().__init__(eligible_votes, quorum_thresh_pct, approval_thresh_pct, against_votes, for_votes, abstain_votes, include_abstain)


class ApprovalTally:

    def __init__(self, eligible_votes, quorum_thresh_pct, approval_thresh_pct, counts, aggregated_support_vp, include_abstain=False):
        """
        eligible_votes: Number of eligible voters (for off-chain) or Votable Supply (for on-chain)
        
        quorum_thresh_pct: Quorum threshold percentage as a float.  Eg. 0.5 for 50%
        approval_thresh_pct: Approval threshold percentage as a float.  Eg. 0.5 for 50%

        votes: Dictionary of choices with votes, where the key is the choice, and then sub-keys are for
        against, for, abstain.  eg.

        {'choice 1' : {'0' : 10, '1' : 20, '2' : 30},
         'choice 2' : {'0' : 10, '1' : 20, '2' : 30}}

        aggregated_support_vp: Dictionary of support without redundantly counting VP.  eg.
        {0 : '1234', 1 : 2500 , 2 : 300000}

        """

        self.choice_tallies = {k : Choice(k, eligible_votes, quorum_thresh_pct, approval_thresh_pct, v, include_abstain) for k, v in counts.items()}

        self.include_abstain = include_abstain

        if self.include_abstain:
            self.total_votes = sum([int(v) for v in aggregated_support_vp.values()])
        else:
            self.total_votes = sum([int(v) for k, v in aggregated_support_vp.items() if k in [0, 1]])
    
        self.eligible_votes = eligible_votes

        self.quorum_thresh_pct = quorum_thresh_pct
        self.approval_thresh_pct = approval_thresh_pct

        if self.total_votes != 0:

            assert self.eligible_votes != 0, "eligible_votes must be non-zero, there should be no reason it's not."

            self.relative_pct = {k : {support : int(vp) / self.total_votes for support, vp in v.items()} for k, v in counts.items()}

            self.absolute_pct = {k : {support : int(vp) / self.eligible_votes for support, vp in v.items()} for k, v in counts.items()}

            self.quorum = self.total_votes / self.eligible_votes
            self.passing_quorum = self.quorum >= self.quorum_thresh_pct

            self.approval = aggregated_support_vp[1] / self.total_votes
            self.passing_approval_threshold = self.approval >= self.approval_thresh_pct

        else:
            self.relative_pct = {k : {support : 0 for support in [0, 1, 2]} for k in self.choice_tallies}
            self.absolute_pct = {k : {support : 0 for support in [0, 1, 2]} for k in self.choice_tallies}
            self.quorum = 0
            self.approval = 0

            self.passing_quorum = self.quorum >= self.quorum_thresh_pct
            self.passing_approval_threshold = self.approval >= self.approval_thresh_pct

    def gen_tally_report(self, label, weight=1, include_quorum=True):

        tally = f"{label} Tally"
        
        if weight < 1:
            tally += f" [{weight:.2%} of Final]\n"
        else:
            tally += "\n"

        tally += "-" * (len(tally) - 1) + "\n"


        tally += f"Total Votes:         {self.total_votes:>32}\n"
        tally += f"Eligible Votes:      {self.eligible_votes:>32}\n"

        for k, choice in self.choice_tallies.items():
            if choice.label == -1 and self.include_abstain:
                tally += f"Abstain {k}:               {choice.abstain_votes:>32} ({choice.abstain_votes / self.total_votes:.1%} of total | {choice.absolute_abstain_pct:.1%} of eligible)\n"
            else:
                tally += f"For {k}:               {choice.for_votes:>32} {bte(self.choice_tallies[choice.label].passing_approval_threshold)} ({self.choice_tallies[choice.label].approval:.1%} of total | {choice.absolute_for_pct:.1%} of eligible)\n"
        
        if include_quorum:
            tally += f"Quorum: {self.quorum:.2%} {bte(self.passing_quorum)} ({self.quorum_thresh_pct:.0%})"

        return tally


class FinalApprovalTally:
    def __init__(self, tallies, weights, quorum_thresh_pct, approval_thresh_pct, include_abstain=False):
        self.tallies = tallies
        self.weights = weights

        self.relative_pct = defaultdict(lambda: defaultdict(float))
        for tally, weight in zip(tallies, weights):
            for choice, choice_tally in tally.relative_pct.items():
                for support, pct in choice_tally.items():
                    self.relative_pct[choice][support] += pct * weight


        self.absolute_pct = defaultdict(lambda: defaultdict(float))
        for tally, weight in zip(tallies, weights):
            for choice, choice_tally in tally.absolute_pct.items():
                for support, pct in choice_tally.items():
                    self.absolute_pct[choice][support] += pct * weight

        self.quorum = sum([t.quorum * w for t, w in zip(tallies, weights)])

        self.approval = 0.0
        for tally, weight in zip(tallies, weights):
            self.approval += tally.approval * weight

        self.quorum_thresh_pct = quorum_thresh_pct
        self.approval_thresh_pct = approval_thresh_pct
   
        self.passing_quorum = self.quorum >= quorum_thresh_pct
        self.passing_approval_threshold = self.approval >= approval_thresh_pct     

        self.include_abstain = include_abstain


    def gen_tally_report(self, label):

        tally = f"{label} Tally\n"
        tally += "-" * (len(tally) - 1) + "\n"

        # tally += f"For: ({self.relative_for_pct:.1%} of total | {self.absolute_for_pct:.1%} of eligible)\n"
        # tally += f"Against: ({self.relative_against_pct:.1%} of total | {self.absolute_against_pct:.1%} of eligible)\n"

        # if self.include_abstain:
        #     tally += f"Abstain: ({self.relative_abstain_pct:.1%} of total | {self.absolute_abstain_pct:.1%} of eligible)\n"

        tally += f"Quorum: {self.quorum:.3%} {bte(self.passing_quorum)} ({self.quorum_thresh_pct:.0%}), Approval: {self.approval:.3%} {bte(self.passing_approval_threshold)} ({self.approval_thresh_pct:.0%}) -> "

        if self.passing_quorum and self.passing_approval_threshold:
            tally += "✅ PASSING\n"
        else:
            tally += "❌ DEFEATED\n"

        return tally



class OnChainApprovalMixin:

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
    
        # pandas doesn't play nice with large ints.
        aggregated_support_vp = onc_votes[['support', 'weight']].groupby('support').apply(bigint_sum).to_dict()
        aggregated_support_vp = { k : int(v) for k, v in aggregated_support_vp.items()}

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
        return ApprovalTally(votable_supply, quorum_thresh_pct, approval_thresh_pct, counts, aggregated_support_vp, include_abstain=True)

class OffChainApprovalMixin:

    def calculate_approval_tallies(self):
        
        assert self.proposal_type_label == 'approval', f"Proposal type is not approval: {self.proposal_type_label}"

        offc_votes = self.offc_votes.copy()
        offc_votes['support'] = 1

        tallies = []

        approval_thresh_pct = (self.proposal_type_info['approval_threshold_bps'] / 10000)
        quorum_thresh_pct = (self.proposal_type_info['quorum_bps'] / 10000)
        
        for category in ['app', 'user', 'chain']:

            cat_offc_votes = offc_votes[offc_votes['SelectionMethod'] == category][['choices', 'weight', 'support']]

            eligible_votes = self.ch_counts[category]

            blank_counts = defaultdict(dict)
            for choice_pos, choice_label in enumerate(self.choice_list):
                for support in [0, 1, 2]:
                    blank_counts[choice_pos][support] = 0
                    
            if len(cat_offc_votes) == 0:
                counts = dict(blank_counts)
                aggregated_support_vp = { k : 0 for k in [0, 1, 2]}
                tallies.append(ApprovalTally(eligible_votes, quorum_thresh_pct, approval_thresh_pct, counts, aggregated_support_vp, include_abstain=True))

            else:

                ballot_feed = cat_offc_votes[['weight', 'support', 'choices']].explode('choices')

                counts = ballot_feed.groupby(['choices', 'support']).apply(np.sum)
                totals = ballot_feed.groupby(['choices'])['weight'].apply(np.sum).to_dict()

                aggregated_support_vp = cat_offc_votes[['support', 'weight']].groupby('support')['weight'].sum().to_dict()
                aggregated_support_vp = { k : int(v) for k, v in aggregated_support_vp.items()}

                for (choice, support), value in counts['weight'].items():
                    blank_counts[choice][support] = value
                counts = dict(blank_counts)

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
            

                tallies.append(ApprovalTally(eligible_votes, quorum_thresh_pct, approval_thresh_pct, counts, aggregated_support_vp, include_abstain=True))
            
        return tallies
