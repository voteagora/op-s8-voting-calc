import argh
import csv, os
from pathlib import Path
from yaml import load, FullLoader
from pprint import pprint
import json
from copy import deepcopy

from .jsonrpc_client import JsonRpcHistHttpClient
from .graphqleas_client import EASGraphQLClient
from web3 import Web3
from collections import defaultdict

from eth_abi import decode

from abifsm import ABISet, ABI
from .utils import camel_to_snake, load_config, get_web3

from .signatures import *
from .calc import *
from .jsonrpc_client import JsonRpcContractCalls

from .attestations import meta as all_meta

import pandas as pd

DATA_DIR = Path(os.getenv('S8_DATA_DIR', 'op_s8_vote_calc/data'))
ABIS_DIR = Path(os.getenv('S8_ABIS_DIR', 'op_s8_vote_calc/abis'))
DEPLOYMENT = os.getenv('S8_DEPLOYMENT', 'test')
    

def download_onchain_data():

    config, _ = load_config()

    gov_address= config['gov']['address']
    token_address= config['token']['address']
    chain_id = config['chain_id']

    rpc = os.getenv('S8_JSON_RPC', config['rpc'])

    if rpc is None:
        raise Exception("S8_JSON_RPC environment variable is not set")

    client = JsonRpcHistHttpClient(rpc)
    client.connect()

    abi = ABI.from_file('gov', ABIS_DIR / DEPLOYMENT / 'gov.json')
    abis = ABISet('op', [abi])

    client.set_abis(abis)

    signatures = [VOTE_CAST_1, VOTE_CAST_WITH_PARAMS_1, PROPOSAL_CREATED_2, PROPOSAL_CREATED_4]

    for signature in signatures:
        client.plan_event(chain_id, gov_address, signature)

    meta = ['block_number', 'transaction_index', 'log_index']

    writers = {}
    for signature in signatures:
        field_names = meta + list(map(camel_to_snake, abis.get_by_signature(signature).fields))
        
        (DATA_DIR / DEPLOYMENT).mkdir(parents=True, exist_ok=True)

        fname = DATA_DIR / DEPLOYMENT / (signature + '.csv')

        fs = open(fname, mode='w', newline='')
        print("Creating/Overwriting: " + str(fname.absolute()))
        writer = csv.DictWriter(fs, fieldnames=field_names)
        writer.writeheader()
        writers[signature] = writer

    for event in client.read(from_block=config['start_block'], to_block=config['end_block']):

        signature = event['signature']

        writer = writers[signature]

        del event['signature']
        del event['sighash']

        if signature == VOTE_CAST_1:
            del event['reason']
            writer.writerow(event)
        elif signature == VOTE_CAST_WITH_PARAMS_1:
            del event['reason']
            event['params'] = event['params'].hex()
            writer.writerow(event)
        else:
            writer.writerow(event)
 

def download_offchain_data():

    _, config = load_config()

    meta = all_meta[DEPLOYMENT]

    vote_client = EASGraphQLClient(config['votes_eas'])
    prop_client = EASGraphQLClient(config['prop_eas'])

    for schema_meta in list(meta.values()):

        if schema_meta.name == 'CreateProposal':
            client = prop_client
        else:
            client = vote_client

        field_names = schema_meta.kwtypes.keys()

        eas_meta = ['attester', 'data', 'expirationTime', 'id', 'ipfsHash', 'isOffchain', 'recipient', 'refUID',  'revocable', 'revocationTime', 'revoked', 'schemaId', 'time', 'timeCreated', 'txid']

        schema = client.get_schemas(schema_meta.schema_id)[0]

        # print(schema_meta.name)

        try:
            assert 'schema' in schema
            #pprint(schema['schema'])
        except Exception as e:
            print(f"❌ Bad schema for {schema_meta.name} [id={schema_meta.schema_id}]")
            continue

        (DATA_DIR / DEPLOYMENT).mkdir(parents=True, exist_ok=True)
        fname = DATA_DIR / DEPLOYMENT / (schema_meta.name + '.csv')
        fs = open(fname, mode='w', newline='')
        print("Creating/Overwriting: " + str(fname.absolute()))
        writer = csv.DictWriter(fs, fieldnames=eas_meta + list(schema_meta.kwtypes.keys()))
        writer.writeheader()

        attestations = client.get_attestations(schema_meta.schema_id)

        for attestation in attestations:

            # One bad attestion, can't be decoded.
            if attestation['id'] == '0x01b52865c05bcadc420c82e14d59cb06ed0f4c5845e948b77c80ea4af599294e':
                continue
                
            try:
                payload = schema_meta.decode(attestation['data'])
            except Exception as e:
                print(f"❌ Bad {schema_meta.name} attestion: {attestation['id']} - {attestation['data']}")
            
            del attestation['decodedDataJson']
            del attestation['data']
            
            attestation.update(payload)
            
            writer.writerow(attestation)

def download_proposal_context():

    on_chain_config, off_chain_config = load_config()
    modules = {v['address'].lower() : v['name'] for v in on_chain_config['gov']['modules']}

    onchain_creates_2 = pd.read_csv(DATA_DIR / DEPLOYMENT / (PROPOSAL_CREATED_2 + '.csv'))
    onchain_creates_4 = pd.read_csv(DATA_DIR / DEPLOYMENT / (PROPOSAL_CREATED_4 + '.csv'))
    onchain_creates = pd.concat([onchain_creates_2, onchain_creates_4])
    onchain_records = onchain_creates.iterrows()

    offchain_creates = pd.read_csv(DATA_DIR / DEPLOYMENT / 'CreateProposal.csv')
    offchain_records = offchain_creates.iterrows()

    w3 = get_web3()    
    jrpc = JsonRpcContractCalls(w3)


    for idx, row in list(onchain_records) + list(offchain_records):

        asof_block_num = row['start_block']
        
        if 'proposal_id' in row:
            proposal_id = row['proposal_id']
            proposal_type_id = row['proposal_type']
            onchain_proposal_id = proposal_id
            tech = "onchain"
        elif 'id' in row:
            proposal_id = row['id']
            proposal_type_id = row['proposal_type_id']
            onchain_proposal_id = row['onchain_proposalid']
            tech = "offchain"
        else:
            raise Exception(f"❌ Bad record: {row}")
        

        if int(onchain_proposal_id) == 0:
            quorum = None
            votable_supply = None
            proposal_type_info = jrpc.get_proposal_type_info(onchain_config['ptc']['address'], proposal_type_id, asof_block_num)
        else:
            quorum = jrpc.get_quorum(onchain_config['gov']['address'], proposal_id)
            votable_supply = jrpc.get_votable_supply(onchain_config['gov']['address'], asof_block_num)
            proposal_type_info = jrpc.get_proposal_type_info(onchain_config['ptc']['address'], proposal_type_id, asof_block_num)
        
        proposal_type_info['module_name'] = modules.get(proposal_type_info['module'].lower(), 'unknown')

        out = {'proposal_id': proposal_id, 
                'asof_block_num': asof_block_num, 
                'proposal_type_id': proposal_type_id, 
                'quorum': quorum, 
                'votable_supply': votable_supply, 
                'proposal_type_info': proposal_type_info}

        fname = DATA_DIR / DEPLOYMENT / (proposal_id + '.json')

        fname.parent.mkdir(parents=True, exist_ok=True)

        fs = open(fname, mode='w', newline='')
        json.dump(out, fs, indent=2)
        fs.close()


def list_proposals():

    prop_lister = ProposalLister.load()
    prop_lister.list_proposals()

    return prop_lister

def calculate(proposal_id: str):

    prop_lister = ProposalLister.load()
    prop = prop_lister.get_proposal(proposal_id)
    prop.load_context()
    prop.show_result()

    return prop

def main():

    argh.dispatch_commands([download_onchain_data, download_offchain_data, download_proposal_context, list_proposals, calculate])


if __name__ == '__main__':
    main()
