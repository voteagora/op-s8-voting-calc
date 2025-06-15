
import json
import os
import logging

from datetime import datetime, timedelta
from collections import defaultdict

from web3 import Web3
from web3.exceptions import Web3RPCError
from abifsm import ABISet, ABI

from utils import camel_to_snake
from signatures import VOTE_CAST_1, VOTE_CAST_WITH_PARAMS_1

logr = logging.getLogger(__name__)

def resolve_block_count_span(chain_id=None):

    target = 2000

    if chain_id is None:
        default_block_span = target
    elif chain_id in (1, 11155111): # Ethereum, Sepolia
        default_block_span = target
    elif chain_id in (10, 11155420): # Optimism, Sepolia Optimism
        default_block_span = target * 6
    else:
        default_block_span = target

    try:
        override = int(os.getenv('ARCHIVE_NODE_HTTP_BLOCK_COUNT_SPAN'))
        assert override > 0
    except:
        override = None
    
    return override or default_block_span

class SubscriptionPlannerMixin:

    def init(self):
        self.subscription_meta = []

        self.abis_set = False

    def set_abis(self, abi_set: ABISet):

        assert not self.abis_set

        self.abis_set = True
        self.abis = abi_set
        self.caster = self.casterCls(self.abis)
    
    def plan(self, signal_type, signal_meta):

        if signal_type == 'event':
            self.plan_event(*signal_meta)
        elif signal_type == 'block':
            self.plan_block(*signal_meta)
        else:
            raise Exception(f"Unknown signal type: {signal_type}")

class JsonRpcHistHttpClientCaster:
    
    def __init__(self, abis):
        self.abis = abis

    def lookup(self, signature):

        abi_frag = self.abis.get_by_signature(signature)
        if abi_frag is None:
            raise Exception(f"Unknown signature: {signature}")
        EVENT_NAME = abi_frag.name       
        contract_events = Web3().eth.contract(abi=[abi_frag.literal]).events
        processor = getattr(contract_events, EVENT_NAME)().process_log

        
        if signature in (VOTE_CAST_1, VOTE_CAST_WITH_PARAMS_1):
        
            def caster_fn(log):
                tmp = processor(log)
                args = {camel_to_snake(k) : v for k,v in tmp['args'].items()}
                args['voter'] = args['voter'].lower()
                return args
    
        else: 

            def bytes_to_str(x):
                if isinstance(x, bytes):
                    return x.hex()
                return x

            def array_of_bytes_to_str(x):
                if isinstance(x, list):
                    return [bytes_to_str(i) for i in x]
                elif isinstance(x, bytes):
                    return bytes_to_str(x)
                return x

            def caster_fn(log):
                tmp = processor(log)
                args = {camel_to_snake(k) : array_of_bytes_to_str(v) for k,v in tmp['args'].items()}
                return args

        return caster_fn

class JsonRpcHistHttpClient(SubscriptionPlannerMixin):

    def __init__(self, url):
        self.url = url
        
        self.init()

        self.casterCls = JsonRpcHistHttpClientCaster

        self.event_subsription_meta = defaultdict(lambda: defaultdict(dict))
        self.block_subsription_meta = []

    def connect(self):
        
        return Web3(Web3.HTTPProvider(self.url))

    def plan_event(self, chain_id, address, signature):

        abi_frag = self.abis.get_by_signature(signature)

        caster_fn = self.caster.lookup(signature)

        cs_address = Web3.to_checksum_address(address)

        # TODO: the abifsm library should clean this up.
        topic = abi_frag.topic
        if topic[:2] != "0x":
            topic = "0x" + topic

        self.event_subsription_meta[chain_id][cs_address][topic] = (caster_fn, signature)

    def is_valid(self):

        if self.url in ('', 'ignored', None):
            ans = False
        else:
            w3 = self.connect()
            ans = w3.is_connected()
        
        if ans:
            print(f"The server '{self.url}' is valid.")
        else:
            print(f"The server '{self.url}' is not valid.")
        
        return ans
    

    def get_paginated_logs(self, w3, contract_address, topics, step, start_block, end_block=None):

        def chunk_list(lst, chunk_size):
            """Split a list into chunks of size `chunk_size`."""
            return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

        topics = chunk_list(list(topics), chunk_size=4)

        logr.info(f"👉 Fetching {len(topics)} topic chunk(s) for {contract_address} from block {start_block}")

        from_block = start_block

        all_logs = []

        while True:

            logs = []

            if end_block is None:
                end_block = w3.eth.block_number

            to_block = min(from_block + step - 1, end_block)  # Ensure we don't exceed the end_block

            for topic_chunk in topics:
                chunk_logs = self.get_logs_by_block_range(w3, contract_address, topic_chunk, from_block, to_block)
                logs.extend(chunk_logs)
            
            if len(logs):
                logr.info(f"Fetched {len(logs)} logs from block {from_block} to {to_block}")
            
            all_logs.extend(logs)

            from_block = to_block + 1

            if from_block > end_block:
                break

        return all_logs

    def get_logs_by_block_range(self, w3, contract_address, event_signature_hash, from_block, to_block,
                                current_recursion_depth=0, max_recursion_depth=2000):
        """
        This is a recursive function that will split itself apart to handle block ranges that exceed the block limit of the external API.

        It is unlikely that this function will ever be called directly, and is instead called by
            the :py:meth:`~.clients.JsonRpcHistHttpClient.get_paginated_logs` function, where additional
            processing is performed.

        :param w3: The web3 object used to interact with the external API.
        :param contract_address: The address of the contract to which the event is emitted.
        :param event_signature_hash: The hash of the event signature.
        :param from_block: The starting block number for the block range.
        :param to_block: The ending block number for the block range.
        :param current_recursion_depth: The current recursion depth of the function. Used for tracking recursion depth.
        :param max_recursion_depth: The maximum recursion depth allowed for the function. If the recursion depth exceeds this value, an exception will be raised. This prevents infinite recursion.
        :returns: A list of logs from the specified block range.
        """

        # Set filter parameters for each range
        event_filter = {
            "fromBlock": from_block,
            "toBlock": to_block,
            "address": contract_address,
            "topics": [event_signature_hash]
        }

        try:
            logs = w3.eth.get_logs(event_filter)
        except Exception as e:
            # catch and attempt to recover block limitation ranges
            if isinstance(e, Web3RPCError):
                error_dict = eval(str(e.args[0]))  # Convert string representation to dict
                api_error_code = error_dict['code']
                if api_error_code == -32600 or api_error_code == -32602:
                    # add one to recursion depth
                    new_recursion_depth = current_recursion_depth + 1
                    # split block range in half
                    mid = (from_block + to_block) // 2
                    # Get results from both recursive calls
                    first_half = self.get_logs_by_block_range(
                        w3=w3,
                        from_block=from_block,
                        to_block=mid - 1,
                        contract_address=contract_address,
                        event_signature_hash=event_signature_hash,
                        current_recursion_depth=new_recursion_depth,
                        max_recursion_depth=max_recursion_depth
                    )

                    second_half = self.get_logs_by_block_range(
                        w3=w3,
                        from_block=mid,
                        to_block=to_block,
                        contract_address=contract_address,
                        event_signature_hash=event_signature_hash,
                        current_recursion_depth=new_recursion_depth,
                        max_recursion_depth=max_recursion_depth
                    )

                    # Combine results, handling potential None values
                    logs = []
                    if first_half is not None:
                        logs.extend(first_half)
                    if second_half is not None:
                        logs.extend(second_half)
                    return logs
            # Fallback to raising the exception
            raise e
        return logs


    def read(self, from_block, to_block):

        w3 = self.connect()

        all_logs = []

        new_signal = True
        for chain_id in self.event_subsription_meta.keys():

            step = resolve_block_count_span(chain_id)

            for cs_address in self.event_subsription_meta[chain_id].keys():

                topics = self.event_subsription_meta[chain_id][cs_address].keys()

                logs = self.get_paginated_logs(w3, cs_address, topics, step, from_block, to_block)

                for log in logs:


                    topic = "0x" + log['topics'][0].hex()

                    caster_fn, signature = self.event_subsription_meta[chain_id][cs_address][topic]

                    args = caster_fn(log)

                    out = {}

                    out['block_number'] = str(log['blockNumber'])
                    out['transaction_index'] = log['transactionIndex']
                    out['log_index'] = log['logIndex']

                    out.update(**args)
                    
                    out['signature'] = signature
                    out['sighash'] = topic.replace("0x", "")

                    all_logs.append(out)

        all_logs.sort(key=lambda x: (x['block_number'], x['transaction_index'], x['log_index']))   

        for log in all_logs:
            yield log
