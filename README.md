# NetPulse Terminal

A dependency-free terminal monitor for up to 15 hosts. It uses Python 3 and the
system `ping` command on macOS or Linux. The live table refreshes in place and
shows status, latest ping, success and failure counts, and minimum, maximum,
and average latency for the current run. Statistics reset on each start.

## Run

```sh
python3 netpulse_term.py
```

Press **Ctrl-C** to stop. Run one cycle with `python3 netpulse_term.py --once`.

## Configure

Edit `settings.json`: set `interval_seconds` and each host's `enabled`, `label`,
and `address`. The file contains 15 empty, disabled entries as a safe starting
point. Use `--settings /path/to/settings.json` to load another configuration.

No packages or virtual environment are required.

## License

MIT. See [LICENSE](LICENSE).
