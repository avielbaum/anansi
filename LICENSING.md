# Licensing

Anansi uses different licences for different parts of the repository. The licence of a file is set by the first match in
this table, from the top.

| Path | Licence | In short |
|---|---|---|
| `examples/*/assets/` | The art's own licence, given in each example's `assets/LICENSE.md` (for example [Waypoint's](examples/waypoint/assets/LICENSE.md): CC-BY-SA 3.0 and CC0) | Third-party art. Credit the authors and follow its terms. |
| `examples/` | MIT OR Apache-2.0, your choice; each example carries `LICENSE-MIT` and `LICENSE-APACHE` | Example games: copy them into any project. |
| `sdk/` | [MIT](sdk/LICENSE-MIT) OR [Apache-2.0](sdk/LICENSE-APACHE), your choice | Ship the SDKs inside any game, free or paid, open or closed. |
| `tools/` | [MIT](tools/LICENSE-MIT) OR [Apache-2.0](tools/LICENSE-APACHE), your choice | Evaluation, red-team and helper scripts. |
| `docs/`, `README.md`, `DESIGN.md`, `LICENSING.md` | [MIT](docs/LICENSE-MIT) OR [Apache-2.0](docs/LICENSE-APACHE), your choice | Documentation. |
| Everything else: `gateway/`, `node/`, `deploy/`, `tests/`, `evals/`, `config*.json`, `assets/logo/` and the other root files | [PolyForm Noncommercial 1.0.0](LICENSE) | The service itself. Free for personal, research, study and other noncommercial use; commercial use needs a separate licence from the licensor. |

Notes:

- The SDKs only talk to a gateway over HTTP. Using an SDK does not put your game under the gateway's licence. Running
  your own gateway, though, is covered by PolyForm Noncommercial, and commercial use of it needs a commercial licence.
- Some scripts in `tools/` (for example `redteam.py` and `mcp_server.py`) import code from `gateway/`. The scripts
  themselves are MIT OR Apache-2.0, but the gateway code they load stays under PolyForm Noncommercial.
- The licences do not grant any rights to the Anansi name or logo.
- Unless you state otherwise, a contribution is licensed under the licence of the part of the repository it changes.
  The licensor may ask contributors to `gateway/` and `node/` to sign a contributor agreement, so that commercial
  licences stay possible.
- Model weights the configs point to (for example Qwen3 or Llama Guard) are not part of this repository and are
  covered by their publishers' licences.
