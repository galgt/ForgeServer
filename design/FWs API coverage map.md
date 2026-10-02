## High‑level map (API coverage vs web console)

### Palo Alto Networks (PAN‑OS / Panorama)

1. **Primary APIs**
    * PAN‑OS REST API (object/policy CRUD, web‑UI‑aligned fields). (docs.paloaltonetworks.com)
    * PAN‑OS XML API (operational commands + broad config; described as “full access to PAN‑OS functionality…almost all” of what the web UI/CLI can do). (docs.paloaltonetworks.com)

2. **Coverage assessment**
    * Near‑full coverage when REST + XML are combined.
    * REST API is designed to mirror web‑UI inputs for configuration objects/policies. (docs.paloaltonetworks.com)
    * XML API explicitly claims broad/near‑full functional coverage (web UI/CLI parity). (docs.paloaltonetworks.com)

3. **Implication**
    If your goal is maximum parity, Palo Alto is the closest to “full coverage,” but you’ll need to use XML for some operational functions beyond REST.

### Fortinet (FortiGate / FortiOS)

1. **Primary APIs**
    FortiGate REST API (configuration CRUD, logs, stats, and basic admin actions). (docs.fortinet.com)

2. **Coverage assessment**
    * Partial/uncertain full parity.
    * Fortinet’s official docs describe scope (config/logs/basic ops) but do not claim full web‑GUI parity. (docs.fortinet.com)

3. **Implication**
    * Assume gaps unless verified in the API reference for each feature.
    * Common in practice: some GUI workflows and “wizard” features are not exposed as first‑class API endpoints, so teams fall back to CLI/automation or FortiManager.

### Check Point (R81.x / R82)

1. **Primary APIs**
    * Management API (policy/objects/management plane).
    * Gaia REST API (OS‑level configuration/ops).

2. **Coverage assessment**
    * Not full coverage.
    * Gaia API explicitly does not support all Gaia OS settings. (sc1.checkpoint.com)
    * Security Management Admin Guide lists API limitations (e.g., Dynamic Layer editing constraints, VSX/VSNext unsupported in that API workflow). (sc1.checkpoint.com)
    * Community‑documented gaps in Management API vs SmartConsole exist (some blades/SmartEvent/SmartUpdate items). (community.checkpoint.com)

3. **Implication**
    * Expect gaps across SmartConsole + Gaia Portal + SmartEvent tooling.
    * You will likely need GUI or CLI for specific blades/features or SmartEvent‑specific work.

## Bottom‑line summary (by vendor)
1. **Palo Alto**: Closest to full coverage if you combine REST + XML; XML API explicitly claims near‑full parity. (docs.paloaltonetworks.com)

2. **Fortinet**: Partial coverage; docs define config/log/ops scope but no official full‑parity claim—treat as “not guaranteed.” (docs.fortinet.com)

3. **Check Point**: Not full coverage; Gaia API lacks some OS settings and Management API has known limitations. (sc1.checkpoint.com)


## To make this actionable, I need a few quick clarifications:
1. Which product lines/management planes?
    * Palo Alto: PAN‑OS only, or Panorama too?
    * Fortinet: FortiGate only, or FortiManager/FortiAnalyzer?
    * Check Point: Single‑Domain/Multi‑Domain Management, SmartEvent, VSX, Gaia?
2. What counts as “web console capabilities” for you?
    Config CRUD, policy install, logs/monitoring, reporting, upgrades, licensing, user mgmt, blades, wizard workflows?
3. Which software versions are in scope?
    API coverage is version‑sensitive; if you tell me versions (e.g., PAN‑OS 11.1, FortiOS 7.6, Check Point R81.20/R82), I’ll refine the map.