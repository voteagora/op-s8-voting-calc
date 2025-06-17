from eth_abi import decode as decode_abi
from .signatures import *

def reverse_engineer_module(signature, proposal_data):

    if signature in (PROPOSAL_CREATED_3, PROPOSAL_CREATED_4):
        crit = '00000000000000000000000000000000000000000000000000000000000000c'
        if proposal_data.startswith(crit):
            return 'approval'
        else:
            return 'optimistic'

    elif signature in (PROPOSAL_CREATED_1, PROPOSAL_CREATED_2):
        return 'standard'
    else:
        raise Exception(f"Unrecognized signature '{signature}'")

def bytes_to_hex(obj):
    if isinstance(obj, bytes):
        return obj.hex()
    elif isinstance(obj, dict):
        return {k: bytes_to_hex(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [bytes_to_hex(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(bytes_to_hex(item) for item in obj)
    else:
        return obj
        
def decode_proposal_data(proposal_type, proposal_data):

    if proposal_type == 'basic':
        return None

    if proposal_data[:2] == '0x':
        proposal_data = proposal_data[2:]
    proposal_data = bytes.fromhex(proposal_data)

    if proposal_type == 'optimistic':
        abi = ["(uint248,bool)"]
        decoded = decode_abi(abi, proposal_data)
        return bytes_to_hex(decoded)
    
    if proposal_type == 'approval':
        abi = ["(uint256,address[],uint256[],bytes[],string)[]", "(uint8,uint8,address,uint128,uint128)"]
        abi2 = ["(address[],uint256[],bytes[],string)[]",        "(uint8,uint8,address,uint128,uint128)"] # OP/alligator only? Only for 0xe1a17f4770769f9d77ef56dd3b92500df161f3a1704ab99aec8ccf8653cae400l

        try:
            decoded = decode_abi(abi, proposal_data)
        except Exception as err:
            decoded = decode_abi(abi2, proposal_data)

        decoded = bytes_to_hex(decoded)
        
        return decoded

    raise Exception("Unknown Proposal Type: {}".format(proposal_type))

