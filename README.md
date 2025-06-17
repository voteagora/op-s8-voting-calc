# Optimism Season 8 Vote Calculator CLI

A command-line interface tool for downloading and calculating vote results for Optimism Season 8 votes.  This was the first season doing mix on and off chain voting.

## Quick Start

### Install Library from Source

```bash
git clone https://github.com/voteagora/op-s8-voting-calc.git
pip install -e .
```

### Point at your Node & Set Contract Deployment

The git repo comes with a config file popupulated with test and main contract deployments.

You'll need to change the RPC endpoints to your own node.

You'll need to set the following environment variables:

```bash
export S8_DATA_DIR=/path/to/data
export S8_DEPLOYMENT=test
export S8_JSON_RPC=https://mainnet.optimism.io
```

And then, depending on your setup you might want to override...

```bash
export S8_CONFIG_DIR=/path/to/config
export S8_ABIS_DIR=/path/to/abis
```

### Download Data

To download data for testnet:

```bash
ops8vote download-onchain-data
ops8vote download-offchain-data
```

To download data for mainnet...

```bash
ops8vote download-onchain-data
ops8vote download-offchain-data
```

### List Proposals

To list proposals for testnet:

```bash
ops8vote list-proposals
```

...should list output like this:

```
Listing all proposals

Off-chain proposals: 2
⛓️‍💥 OPTIMISTIC_TIERED: id=49797297374388153297865929838159354763856732192382468650058430624104400238833, title=# Jeff - Offchain Only - Optimistic Tier - June 12 10:15 AM
⛓️‍💥 APPROVAL: id=95647532391336425113284705305810426138679226160678387259848355019474222496950, title=# Sudheer: Test Approval Hybrid Proposal

On-chain proposals: 12
⛓️ BASIC: id=14600090851423888673871144218032166327714904352414268808281169441053048962838, title=# [TEST] - pedro 2025-06-03
⛓️ BASIC: id=49313948667796903603360051850227879680520673392082756130951136683634837819266, title=# cancel basic proposal
⛓️ BASIC: id=32426287155913904840488684818334451818043191670420267452900409518566735216130, title=# basic proposal test test
⛓️ BASIC: id=107980623708671572031503393241994673286648883753261270183539274298960229801779, title=# [TEST] - Garrett - (hybrid-basic-default)
⛓️ OPTIMISTIC: id=56834676367243609725554333961377273861955503468300131824545453547974825038258, title=# optimistic proposal test
⛓️ APPROVAL: id=8600146195258290332354057058134045663599751773456849155400214660349548074484, title=# Sudheer: test approval
⛓️ APPROVAL: id=52891225558001836125090117863746749148949199604573636273003710557410723970724, title=# Sudheer: test 2 approval
⛓️ APPROVAL: id=74734582045615567809205364448671057492132719354025396846632119831303961734100, title=# Jeff June 9 5 PM ET - Approval
⛓️ APPROVAL: id=91961788125326291196446230006627671565252344591055004834498323935236959069326, title=# [TEST] - pedro 2025-06-09
⛓️ APPROVAL: id=16668477007700866414750848325506268050228703942365698923937803438375005579669, title=# Jeff - Hybrid + Approval + Alt-Approval + 5:41 PM Jun 9 
⛓️ OPTIMISTIC: id=13629638228520827275286951352817746886846092300854597400370075494346395706005, title=# Pedro - test collapsed proposal page 2025-06-10 1
⛓️ APPROVAL: id=49081122109348338420643191503268752102175318210025958297140660061189210432391, title=# Sudheer: Test Approval Hybrid Proposal

Hybrid proposals: 1
☯️ BASIC: id=112542233745806009107871466048611490894875302937505011175151532497811941558355-42740012529150791772311325945937601588484139798594959324533215350132958331528, title=# Jeff - Hybrid + Basic + June 12 9:26 AM ET
```

### Calculate a Specific Proposal's Result

```bash
ops8vote calculate 112542233745806009107871466048611490894875302937505011175151532497811941558355-42740012529150791772311325945937601588484139798594959324533215350132958331528
```

Should output something like...

```
Calculating result for proposal 112542233745806009107871466048611490894875302937505011175151532497811941558355-42740012529150791772311325945937601588484139798594959324533215350132958331528

☯️ BASIC: id=112542233745806009107871466048611490894875302937505011175151532497811941558355-42740012529150791772311325945937601588484139798594959324533215350132958331528, title=# Jeff - Hybrid + Basic + June 12 9:26 AM ET

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

And an example approval proposal...

```
⛓️ APPROVAL: id=21837554113321175128753313420738380328565785926226611271713131734865736260549, title=# Rolling Mission Requests: Voting Cycle 27

Token House Tally
-----------------
Given 46938802908591101013645634 total votes, and 96501702642209702712786254 eligible votes... 
Abstain: 6515768095338571250010090 (13.9% of total | 6.8% of eligible)
For: 31431910661813432620160489 ✅ (67.0% of total | 32.6% of eligible)
For: 35035962495117270703561571 ✅ (74.6% of total | 36.3% of eligible)
For: 17033284171118898054256072 ❌ (36.3% of total | 17.7% of eligible)
For: 17663853612321229474897508 ❌ (37.6% of total | 18.3% of eligible)
For: 24934837283900123569914475 ✅ (53.1% of total | 25.8% of eligible)
For: 28476520065880757383430022 ✅ (60.7% of total | 29.5% of eligible)
For: 23272354186448414025424072 ❌ (49.6% of total | 24.1% of eligible)
For: 21779420495943287974126505 ❌ (46.4% of total | 22.6% of eligible)
Quorum: 48.64% ✅ (30%)
```


## Summary of Usage

The CLI provides the following commands:

1. Download on-chain data:
```bash
python cli.py download-onchain-data
```

2. Download EAS data:
```bash
python cli.py download-offchain-data
```

3. List proposals:
```bash
python cli.py list-proposals
```

4. Calculate result for a specific proposal:
```bash
python cli.py calculate-result $PROPOSAL_ID
```


### Feature Support

- [x] Beta Test Config
- [ ] Final Test Config
- [ ] Beta Main Config
- [ ] Final Main Config

- [x] Dynamic Proposal Type Support - The idea that proposal types are point-in-time aware, based on the proposal start time.
- [x] calculationOptions Support - allowing toggling of "include abstain" in basic tallies.
- [x] Citizen Registration Status (ie, unrevoked)
- [ ] Citizen Wallet Changes

Basic Proposals:
 - [x] Onchain
 - [x] Offchain
 - [x] Hybrid

Approval Proposals:
 - [x] Onchain
 - [ ] Offchain
 - [ ] Hybrid

Optimistic Proposals:
 - [ ] Onchain
 - [ ] Offchain
 - [ ] Hybrid

Optimistic Tiered Proposals:
 - [ ] Onchain
 - [ ] Offchain
 - [ ] Hybrid

 