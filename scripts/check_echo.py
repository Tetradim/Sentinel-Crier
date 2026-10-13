"""Run a generated synthetic entry through an external Echo checkout. Read-only."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crier.cards import render
from crier.models import Settings
from crier.samples import sample

parser = argparse.ArgumentParser()
parser.add_argument("echo_backend", type=Path)
args = parser.parse_args()
sys.path.insert(0, str(args.echo_backend.resolve()))
from utils import parse_alert

content = render(sample("option_buy"), Settings(format="echo"))["content"]
parsed = parse_alert(content)
assert parsed and parsed["alert_type"] == "buy"
assert parsed["ticker"] == "SPY" and parsed["strike"] == 600
assert parsed["option_type"] == "CALL" and parsed["entry_price"] == 1.25
print("Generated BTO entry parsed successfully. This does not verify Echo sizing or execution.")
