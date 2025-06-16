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
from .utils import camel_to_snake, load_config

from .signatures import *
from .calc import *

from .attestations import meta as all_meta

import pandas as pd

DATA_DIR = Path(os.getenv('S8_DATA_DIR', 'op_s8_vote_calc/data'))
ABIS_DIR = Path(os.getenv('S8_ABIS_DIR', 'op_s8_vote_calc/abis'))
    

def download_onchain_data(env='main'):

    config, _ = load_config(env)

    gov_address= config['gov']['address']
    token_address= config['token']['address']
    chain_id = config['chain_id']

    rpc = config['rpc']

    client = JsonRpcHistHttpClient(rpc)
    client.connect()

    abi = ABI.from_file('gov', ABIS_DIR / env / 'gov.json')
    abis = ABISet('op', [abi])

    client.set_abis(abis)

    signatures = [VOTE_CAST_1, VOTE_CAST_WITH_PARAMS_1, PROPOSAL_CREATED_2, PROPOSAL_CREATED_4]

    for signature in signatures:
        client.plan_event(chain_id, gov_address, signature)

    meta = ['block_number', 'transaction_index', 'log_index']

    writers = {}
    for signature in signatures:
        field_names = meta + list(map(camel_to_snake, abis.get_by_signature(signature).fields))
        
        (DATA_DIR / env).mkdir(parents=True, exist_ok=True)

        fname = DATA_DIR / env / (signature + '.csv')

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
 

def download_offchain_data(env='main'):

    _, config = load_config(env)

    meta = all_meta[env]

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
            pprint(schema['schema'])
        except Exception as e:
            print(f"❌ Bad schema for {schema_meta.name} [id={schema_meta.schema_id}]")
            continue

        (DATA_DIR / env).mkdir(parents=True, exist_ok=True)
        fname = DATA_DIR / env / (schema_meta.name + '.csv')
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


def list_proposals(env='main'):

    prop_lister = ProposalLister.load(env)
    prop_lister.list_proposals()

    return prop_lister

def calculate(proposal_id: str, env='main'):

    on_chain_config, off_chain_config = load_config(env)

    prop_lister = ProposalLister.load(env)
    prop = prop_lister.get_proposal(proposal_id)

    if isinstance(prop, (Hybrid, OnChain)):
        w3 = Web3(Web3.HTTPProvider(on_chain_config['rpc']))
        prop.load_onchain_context(env, w3, on_chain_config['gov']['address'])
    
    if isinstance(prop, (Hybrid, OffChain)):
        prop.load_offchain_context(env)
    
    prop.show_result()

    return prop

def main():

    argh.dispatch_commands([download_onchain_data, download_offchain_data, list_proposals, calculate])


if __name__ == '__main__':
    main()
