
import requests as r
from typing import List
from pprint import pprint

class EASGraphQLClient:

    def __init__(self, url):
        self.url = url
    
    def get_schemas(self, schema_id) -> List:
        QUERY = """
                query GetSchema($where: SchemaWhereUniqueInput!) {
                getSchema(where: $where) {
                    id
                    index
                    resolver
                    revocable
                    schema
                    time
                    txid
                    creator
                }
                }
                """

        VARIABLES = {
            "where": {"id": schema_id}
        }

        # print(f"Hitting: {self.url}")
        resp = r.post(self.url, json={'query': QUERY , 'variables': VARIABLES})
        
        return [resp.json()['data']['getSchema']]

    def get_attestations(self, schema_id):

        take = 100
        skip = 0

        while True:
            QUERY = """
                    query Attestations($where: AttestationWhereInput, $take: Int, $skip: Int) {
                    attestations(where: $where, take: $take, skip: $skip) {
                        id
                        ipfsHash
                        isOffchain
                        recipient
                        refUID
                        expirationTime
                        decodedDataJson
                        data
                        attester
                        revocable
                        revocationTime
                        revoked
                        time
                        timeCreated
                        txid
                        schemaId
                    }
                    }
                    """
            VARIABLES = {
                "where": {
                    "schemaId": { "equals": schema_id }
                },
                "take" : take,
                "skip" : skip
            }
            resp = r.post(self.url, json={'query': QUERY , 'variables': VARIABLES})

            attestations = resp.json()['data']['attestations']

            for attestation in attestations:
                yield attestation

            if len(attestations) == take:
                skip = skip + take
            else:
                break