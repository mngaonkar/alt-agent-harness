---
name: coinbase-cli
description: Install and use the Coinbase CLI to trade crypto, US Derivatives (Futures), and US equities, manage portfolios, check prices, and convert currencies on Coinbase Advanced Trade. Use when the user wants to check crypto or derivative prices, place or preview orders (spot, futures, or equities), manage portfolios, transfer funds between portfolios, convert USDC/USD, or set up headless Coinbase access for an AI agent — even if they don't explicitly say "CLI."
version: 1.0.0
---

# Coinbase CLI

Headless access to Coinbase Advanced Trade. Install once, authenticate with a CDP API key, trade with JSON output.

Source: https://docs.cdp.coinbase.com/coinbase-for-agents/skill.md

## Installation

```bash
node --version   # must be >= 22
npm i -g @coinbase/coinbase-cli
coinbase --version
```

Linux only — keyring: `which secret-tool || sudo apt install -y libsecret-tools`

nvm/fnm: reinstall global packages after Node upgrades.

This host: Node v23.11.0, Darwin (skip libsecret), CLI 0.0.7 installed at global npm.

## Authentication

1. Sign in at https://portal.cdp.coinbase.com/api-keys/secret
2. Create API Key (name e.g. `my-trading-agent`)
3. Advanced Settings > Coinbase App & Advanced Trade: select portfolio; enable Trade and Transfer; opt out of IP allowlisting if needed. US Derivatives only work in the **default** portfolio.
4. Create & Download JSON key file

```bash
coinbase env live --key-file <path-to-key.json>
coinbase env
coinbase balance
```

Do not invent keys. If no key file is provided, stop and ask the user for the JSON path.

## Core commands (run via run_bash)

Market: `coinbase products get <id>`, `list`, `ticker`, `book`, `candles`, `best-bid-ask`
Orders: `preview`, `create` (always `client_order_id=$(uuidgen)`), `list`, `get`, `fills`, `edit`, `cancel`, `close-position`
Portfolios: `coinbase balance`, `portfolios list|get|create|edit|delete`, `transfer`
Convert: `convert quote|execute|get`
Info: `coinbase fees`, `env`, `mcp`

## Agent-critical flags

- `--template` before first use of a command
- `--dry-run` before writes
- `--jq <expr>` to shrink JSON
- `-e <env>` to override environment

Field syntax: `key=value` string, `key:=value` raw JSON, `key==value` query, `@file.json` body file.

## Safety

Preview before create. Never place live orders unless the user explicitly asked. Do not write exploits or attack systems.
