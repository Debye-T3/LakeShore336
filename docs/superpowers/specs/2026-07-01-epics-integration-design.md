# Lake Shore 336 EPICS Integration Design

## Goal

Turn the existing Lake Shore 336 project into a production EPICS device integration that can participate in a unified beamline control system.

The EPICS IOC becomes the only process allowed to communicate with the instrument. Operator interfaces, automation, and temporary logging use EPICS PVs. The existing direct Python ZIP remains an emergency commissioning tool and may be used only while the IOC is stopped.

## Delivery Phases

### Phase 1: Complete EPICS control over USB

- Develop and test in WSL Ubuntu.
- Use the existing USB virtual serial interface.
- Expand the IOC to match the validated core functions of the web controller.
- Add guarded, ordered control transactions and explicit readback verification.
- Provide standard Channel Access PVs without committing to a beamline UI framework.
- Move CSV logging to a separate EPICS client process.

### Phase 2: Linux production and Ethernet

- Deploy the same IOC source on the beamline Linux IOC host.
- Replace the asyn serial port with `drvAsynIPPortConfigure`.
- Connect to the Model 336 TCP socket on port 7777.
- Preserve the PV names, protocol commands, safety behavior, and client interfaces.

### Later beamline expansion

Other beamline devices receive separate IOC modules and independent PV namespaces. They reuse the same conventions for health, permissions, transaction state, access security, logging, and commissioning. They are not added directly to the Lake Shore IOC.

## System Boundaries

```text
Future beamline UI / automation / CSV logger
                    |
              EPICS Channel Access
                    |
             Lake Shore 336 IOC
       validation, permission, transaction,
        hardware readback, alarms, status
                    |
        Phase 1: asyn serial over USB
        Phase 2: asyn TCP over Ethernet
                    |
             Lake Shore Model 336
```

Rules:

- The IOC is the single hardware owner.
- The Python logger never sends instrument commands.
- The direct ZIP must not run concurrently with the IOC.
- WSL is a development environment; the production target is Linux.
- The PV prefix is configurable. Development defaults to `LS336:`; production supplies the beamline prefix at startup.

## Public PV Contract

All names below are relative to configurable macro `$(P)`.

### Identity and IOC health

| PV | Type | Purpose |
|---|---|---|
| `IDN` | stringin | Instrument identity |
| `COMM:STATUS` | mbbi | `Unknown`, `Connected`, or `Error` |
| `ERR` | stringin | Last IOC or transaction error |
| `IOC:VERSION` | stringin | IOC software version |
| `IOC:HEARTBEAT` | longin | Incrementing IOC heartbeat |

### Temperature inputs and software mappings

| PV | Type | Purpose |
|---|---|---|
| `Input:A:TEMP_RBV` | ai | Input A temperature |
| `Input:B:TEMP_RBV` | ai | Input B temperature |
| `Input:C:TEMP_RBV` | ai | Input C temperature |
| `Input:D:TEMP_RBV` | ai | Input D temperature |
| `ColdHead:INPUT` | mbbo | Software source mapping, A-D |
| `ColdHead:TEMP_RBV` | ai | Temperature selected by `ColdHead:INPUT` |
| `Sample:INPUT` | mbbo | Software source mapping, A-D |
| `Sample:TEMP_RBV` | ai | Temperature selected by `Sample:INPUT` |

`ColdHead:INPUT` and `Sample:INPUT` do not send hardware commands. Startup macros initialize them to A and B. Runtime persistence through autosave is outside Phase 1.

### Loop 1 staged commands

| PV | Type | Validation |
|---|---|---|
| `Loop1:CTRL:ENABLE` | bo | Defaults to Off on every IOC start |
| `Loop1:INPUT` | mbbo | A-D |
| `Loop1:SETP` | ao | 0-350 K |
| `Loop1:RAMP:ENABLE` | bo | Off or On |
| `Loop1:RAMP:RATE` | ao | 0-10 K/min |
| `Loop1:RANGE` | mbbo | Off, Low, Medium, or High |
| `Loop1:APPLY` | bo | Triggers one guarded transaction |

These command PVs are staging values. Writing them never talks to the instrument. Only `Loop1:APPLY` may cause hardware writes.

`Loop1:CTRL:ENABLE` remains enabled until explicitly disabled or the IOC restarts. It is not persisted.

### Loop 1 readbacks and transaction status

| PV | Type | Purpose |
|---|---|---|
| `Loop1:INPUT_RBV` | mbbi | Hardware control input from `CSET? 1` |
| `Loop1:SETP_RBV` | ai | Hardware setpoint |
| `Loop1:RAMP:ENABLE_RBV` | bi | Hardware ramp state |
| `Loop1:RAMP:RATE_RBV` | ai | Hardware ramp rate |
| `Loop1:RANGE_RBV` | mbbi | Hardware heater range |
| `Loop1:HTR_RBV` | ai | Heater output percentage |
| `Loop1:PID:P_RBV` | ai | PID proportional readback |
| `Loop1:PID:I_RBV` | ai | PID integral readback |
| `Loop1:PID:D_RBV` | ai | PID derivative readback |
| `Loop1:APPLY:STATE` | mbbi | Transaction state |
| `Loop1:APPLY:MSG` | stringin | Human-readable result |

`Loop1:APPLY:STATE` values are:

1. `Idle`
2. `Busy`
3. `Success`
4. `Disabled`
5. `Rejected`
6. `Mismatch`
7. `Error`

PID writes, sensor curves, alarm configuration, and outputs 2-4 are excluded from Phase 1. PID maintenance continues through the direct tool with the IOC stopped.

Internal StreamDevice hardware-write records are implementation details and are not part of the supported public PV API.

## APPLY Transaction

The IOC uses an EPICS Sequencer SNL program as the transaction coordinator. The setup process adds the EPICS Sequencer module as an explicit dependency.

When `Loop1:APPLY` is processed:

1. Reject the request if another transaction is `Busy`.
2. Snapshot all staged command PVs.
3. Require `CTRL:ENABLE=On`.
4. Require valid input, setpoint, ramp, and range values.
5. Require instrument communication to be healthy.
6. Set state to `Busy` and clear the prior message.
7. Send hardware commands with 150 ms between commands:
   - Requested range Off: send `RANGE 1,0` first.
   - Send `CSET 1,<input>,1,1`.
   - Send `RAMP 1,<enable>,<rate>`.
   - Send `SETP 1,<setpoint>`.
   - Requested range Low/Medium/High: send `RANGE 1,<range>` last.
8. Wait 500 ms, then force fresh readback processing.
9. Compare input, ramp enable, and range exactly.
10. Compare setpoint within 0.01 K and ramp rate within 0.001 K/min.
11. Publish `Success`, `Mismatch`, or `Error` and a diagnostic message.
12. Return `Loop1:APPLY` to zero.

No automatic command retry occurs after a communication failure because the instrument may have accepted only part of the transaction. Staged values remain unchanged so the operator can inspect and deliberately retry.

## Communication and Alarms

- All required readbacks scan every two seconds.
- Startup status is `Unknown`.
- Status becomes `Connected` only after required readbacks complete without communication alarms.
- A read timeout or StreamDevice failure sets the affected record alarm and `COMM:STATUS=Error`.
- `ERR` and `APPLY:MSG` identify disabled control, validation rejection, readback mismatch, and communication failure.
- IOC restart resets `CTRL:ENABLE=Off`, `APPLY:STATE=Idle`, and clears any in-progress transaction.
- Ethernet migration preserves CR/LF command termination and the existing Lake Shore command set.

## Access Security

Development startup may use permissive access. Production includes an EPICS Access Security file:

- All permitted beamline clients may read public PVs.
- Only approved hosts/users may write software mappings and staged command PVs.
- `CTRL:ENABLE` and `APPLY` use the restricted control group.
- Internal hardware-write records are not remotely writable.
- The repository's production template denies remote control writes by default and permits localhost commissioning only. Deployment must supply the beamline host/user allowlist before remote control is enabled.

Access Security complements instrument limits and beamline interlocks; it does not replace them.

## Temporary EPICS CSV Logger

The current archive behavior becomes a separate Python EPICS client service:

- It reads PVs only and has no serial or socket device client.
- It writes one coherent snapshot every two seconds while the IOC is connected.
- On connection loss it writes one transition row with blank numeric values and `comm=Disconnected`, then resumes normal rows after reconnection.
- Daily filenames use Beijing dates.
- CSV contains only `timestamp_local` with an explicit `+08:00` offset.
- Metadata records timezone, PV prefix, IOC endpoint, software version, schema, sessions, and connection transitions.

CSV fields are:

```text
timestamp_local
cold_head_K
sample_K
input_a_K
input_b_K
input_c_K
input_d_K
control_input
setpoint_K
ramp_enable
ramp_rate_K_per_min
heater_range
heater_percent
pid_p
pid_i
pid_d
comm
apply_state
stable_state
```

Before appending, the logger compares the existing header with the current schema. If it differs, it creates the next available versioned pair, such as:

```text
ls336_temperature_20260701_v2.csv
ls336_temperature_20260701_v2.meta.json
```

It never appends rows to an incompatible schema. Archiver Appliance can later replace this temporary service without changing the IOC PV contract.

## Testing and Acceptance

### Static and unit tests

- Required public PVs and exclusions.
- StreamDevice commands and parsers for `KRDG?`, `CSET?`, `SETP?`, `RAMP?`, `RANGE?`, `PID?`, and `HTR?`.
- Limit validation and access-security declarations.
- Logger field order, Beijing timestamps, schema migration, disconnect transitions, and metadata.

### IOC integration with mock instrument

A Linux pseudo-terminal mock implements the Model 336 command subset and records every received command.

Verify:

- A-D temperatures and all Loop 1 readbacks.
- No hardware writes while disabled or rejected.
- Exact command order and 150 ms minimum spacing.
- Range Off occurs first; nonzero range occurs last.
- Success after matching readbacks.
- Mismatch after deliberately stale or altered readbacks.
- Error and no retry after an injected timeout.
- Communication alarms recover after reconnection.

### Hardware commissioning over USB

- Compare all A-D readings and Loop 1 readbacks with the front panel.
- Confirm staged PV writes alone cause no hardware change.
- Apply a beamline-approved safe transaction.
- Verify readbacks and front-panel values.
- Test range Off before any real heating test.
- Disconnect USB and verify alarms, status, error message, logger transition, and recovery.
- Confirm the direct ZIP cannot be used operationally until the IOC is stopped.

### Deployment rehearsal

- Build and run the same IOC on a Linux host.
- Apply the production prefix and Access Security file.
- Run Channel Access checks from another beamline computer.
- Verify the CSV logger can run independently of the IOC process.

Phase 2 starts only after all USB acceptance checks pass. Ethernet acceptance repeats the same PV and transaction tests against `IP:7777`; no client-facing PV changes are allowed.

## Implementation Boundaries

Phase 1 modifies the IOC database, protocol, startup/build configuration, adds the SNL transaction coordinator, adds a mock instrument, and converts logging to an EPICS client.

It does not build a unified beamline UI, integrate unrelated beamline hardware, deploy Archiver Appliance, persist configuration through autosave, or expose high-risk PID/curve/alarm writes.

## Assumptions

- Phase 1 controls Loop 1 only.
- Input readings and staged setpoints use kelvin.
- Existing 350 K and 10 K/min software limits remain the approved commissioning defaults.
- The Model 336 firmware supports the documented `KRDG?`, `CSET`, `SETP`, `RAMP`, `RANGE`, `PID`, and `HTR` commands.
- EPICS Base, asyn, StreamDevice, and EPICS Sequencer are installed under the existing `/opt/epics` support layout.
- Production supplies the final PV prefix, Ethernet address, and Access Security allowlist without changing the public PV contract.
