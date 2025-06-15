# Vote Calculator CLI

A command-line interface tool for downloading and calculating vote results.

## Installation

```bash
pip install -r requirements.txt
```

## Usage

The CLI provides the following commands:

1. Download on-chain data:
```bash
python cli.py download-onchain-data [test|prod]
```

2. Download EAS data:
```bash
python cli.py download-eas-data [test|prod]
```

3. List proposals:
```bash
python cli.py list-proposals
```

4. Calculate result for a specific proposal:
```bash
python cli.py calculate-result PROPOSAL_ID
```

5. Calculate results for all proposals:
```bash
python cli.py calculate-results
```
