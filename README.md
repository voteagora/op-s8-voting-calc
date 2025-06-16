# Optimism Season 8 Vote Calculator CLI

A command-line interface tool for downloading and calculating vote results for Optimism Season 8 votes.  This was the first season doing mix on and off chain voting.

## Quick Start

### Install Library from Source

```bash
git clone https://github.com/voteagora/op-s8-voting-calc.git
pip install -e .
```

### Point at your Node

The git repo comes with a config file popupulated with test and main contract deployments.

You'll need to change the RPC endpoints to your own node.

### Download Data

To download data for testnet:

```bash
ops8vote download-onchain-data test
ops8vote download-offchain-data test 
```

To download data for mainnet...

```bash
ops8vote download-onchain-data
ops8vote download-offchain-data
```

Note the convention is that `main` is the default.

### List Proposals

To list proposals for testnet:

```bash
ops8vote list-proposals test
```

...should list output like this:

```
Listing all proposals

Off-chain proposals: 2
⛓️‍💥 OPTIMISTIC_TIERED: id=49797297374388153297865929838159354763856732192382468650058430624104400238833, title=# Jeff - Offchain Only - Optimistic Tier - June 12 10:15 AM
⛓️‍💥 APPROVAL: id=95647532391336425113284705305810426138679226160678387259848355019474222496950, title=# Sudheer: Test Approval Hybrid Proposal

On-chain proposals: 12
⛓️ STANDARD: id=14600090851423888673871144218032166327714904352414268808281169441053048962838, title=# [TEST] - pedro 2025-06-03
⛓️ STANDARD: id=49313948667796903603360051850227879680520673392082756130951136683634837819266, title=# cancel basic proposal
⛓️ STANDARD: id=32426287155913904840488684818334451818043191670420267452900409518566735216130, title=# basic proposal test test
⛓️ STANDARD: id=107980623708671572031503393241994673286648883753261270183539274298960229801779, title=# [TEST] - Garrett - (hybrid-basic-default)
⛓️ OPTIMISTIC: id=56834676367243609725554333961377273861955503468300131824545453547974825038258, title=# optimistic proposal test
⛓️ APPROVAL: id=8600146195258290332354057058134045663599751773456849155400214660349548074484, title=# Sudheer: test approval
⛓️ APPROVAL: id=52891225558001836125090117863746749148949199604573636273003710557410723970724, title=# Sudheer: test 2 approval
⛓️ APPROVAL: id=74734582045615567809205364448671057492132719354025396846632119831303961734100, title=# Jeff June 9 5 PM ET - Approval
⛓️ APPROVAL: id=91961788125326291196446230006627671565252344591055004834498323935236959069326, title=# [TEST] - pedro 2025-06-09
⛓️ APPROVAL: id=16668477007700866414750848325506268050228703942365698923937803438375005579669, title=# Jeff - Hybrid + Approval + Alt-Approval + 5:41 PM Jun 9 
⛓️ OPTIMISTIC: id=13629638228520827275286951352817746886846092300854597400370075494346395706005, title=# Pedro - test collapsed proposal page 2025-06-10 1
⛓️ APPROVAL: id=49081122109348338420643191503268752102175318210025958297140660061189210432391, title=# Sudheer: Test Approval Hybrid Proposal

Hybrid proposals: 1
☯️ STANDARD: id=112542233745806009107871466048611490894875302937505011175151532497811941558355-42740012529150791772311325945937601588484139798594959324533215350132958331528, title=# Jeff - Hybrid + Basic + June 12 9:26 AM ET
```

### Calculate a Specific Proposal's Result

```bash
ops8vote calculate test 112542233745806009107871466048611490894875302937505011175151532497811941558355-42740012529150791772311325945937601588484139798594959324533215350132958331528
```

Should output...

```
Calculating result for proposal 112542233745806009107871466048611490894875302937505011175151532497811941558355-42740012529150791772311325945937601588484139798594959324533215350132958331528

☯️ STANDARD: id=112542233745806009107871466048611490894875302937505011175151532497811941558355-42740012529150791772311325945937601588484139798594959324533215350132958331528, title=# Jeff - Hybrid + Basic + June 12 9:26 AM ET

Token House Tally [50.00% of Final]
-----------------------------------
Given 100000000000000000000000 total votes, and 1100000000000000000000000 eligible votes... 
For: 100000000000000000000000 (100.0% of total | 9.1% of eligible)
Against: 0 (0.0% of total | 0.0% of eligible)
Quorum: 9.09% ❌ (30%), Approval: 100.00% ✅ (51%) -> ❌ DEFEATED

Citizen House - Apps Tally [16.67% of Final]
--------------------------------------------
Given 1 total votes, and 100 eligible votes... 
For: 0 (0.0% of total | 0.0% of eligible)
Against: 1 (100.0% of total | 1.0% of eligible)
Quorum: 1.00% ❌ (30%), Approval: 0.00% ❌ (51%) -> ❌ DEFEATED

Citizen House - Users Tally [16.67% of Final]
---------------------------------------------
Given 1 total votes, and 10000 eligible votes... 
For: 0 (0.0% of total | 0.0% of eligible)
Against: 1 (100.0% of total | 0.0% of eligible)
Quorum: 0.01% ❌ (30%), Approval: 0.00% ❌ (51%) -> ❌ DEFEATED

Citizen House - Chains Tally [16.67% of Final]
----------------------------------------------
Given 0 total votes, and 15 eligible votes... 
For: 0 (0.0% of total | 0.0% of eligible)
Against: 0 (0.0% of total | 0.0% of eligible)
Quorum: 0.00% ❌ (30%), Approval: 0.00% ❌ (51%) -> ❌ DEFEATED

Final Tally
-----------
For: (50.0% of total | 4.5% of eligible)
Against: (33.3% of total | 0.2% of eligible)
Quorum: 4.714% ❌ (30%), Approval: 50.000% ❌ (51%) -> ❌ DEFEATED
```


## Summary of Usage

The CLI provides the following commands:

1. Download on-chain data:
```bash
python cli.py download-onchain-data [test|main]
```

2. Download EAS data:
```bash
python cli.py download-offchain-data [test|main]
```

3. List proposals:
```bash
python cli.py list-proposals [test|main]
```

4. Calculate result for a specific proposal:
```bash
python cli.py calculate-result [test|main] PROPOSAL_ID
```
