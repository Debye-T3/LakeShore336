# Lake Shore 336 Simplified EPICS Phase 1 Design

## Goal

Build a small, standard EPICS IOC that reliably reads and controls the Lake Shore 336 over its USB virtual serial port.

Phase 1 proves that the controller can participate in a future unified beamline control system. It does not build the final production safety, archiving, security, or user-interface infrastructure.

## Architecture

```text
caget / caput / future beamline client
                  |
            EPICS records
                  |
            StreamDevice
                  |
          asyn serial over USB
                  |
          Lake Shore Model 336
```

The IOC is the only process allowed to open the instrument connection.

- The existing direct-control ZIP and direct serial logger remain available for maintenance.
- They may run only while the IOC is stopped.
- Phase 1 does not convert the existing logger to an EPICS client.
- Development and USB commissioning run in WSL Ubuntu.
- Production deployment to a Linux IOC host and Ethernet transport are later phases.
- The PV prefix remains configurable, with `LS336:` as the development default.

## Phase 1 Public PVs

All names are relative to `$(P)`.

### Identity and communication

| PV | Access | Meaning |
|---|---|---|
| `IDN` | read | Instrument identity |
| `COMM:STATUS` | read | `Disconnected`, `Connected`, or `Error` |
| `ERR` | read | Most recent generic IOC validation or communication summary |

Detailed timeout, write, read, disconnect, and parse failures are exposed through each StreamDevice record's `STAT` and `SEVR`. Phase 1 does not build a separate detailed error state machine.

### Temperature readbacks

| PV | Access | Meaning |
|---|---|---|
| `Input:A:TEMP_RBV` | read | Input A temperature |
| `Input:B:TEMP_RBV` | read | Input B temperature |
| `Input:C:TEMP_RBV` | read | Input C temperature |
| `Input:D:TEMP_RBV` | read | Input D temperature |
| `ColdHead:TEMP_RBV` | read | Compatibility alias for Input A |
| `Sample:TEMP_RBV` | read | Compatibility alias for Input B |

`ColdHead:TEMP_RBV` and `Sample:TEMP_RBV` are true EPICS record aliases of the A and B records. They do not create independent records or additional `KRDG?` queries. Runtime mapping controls are deferred.

### Loop 1

| PV | Access | Meaning |
|---|---|---|
| `Loop1:INPUT_RBV` | read | Control input parsed from `OUTMODE? 1` |
| `Loop1:SETP` | write | Setpoint command, 0-350 K |
| `Loop1:SETP_RBV` | read | Setpoint from `SETP? 1` |
| `Loop1:RAMP:ENABLE` | write | Ramp Off/On command |
| `Loop1:RAMP:ENABLE_RBV` | read | Ramp state from `RAMP? 1` |
| `Loop1:RAMP:RATE` | write | Ramp rate command, 0-10 K/min |
| `Loop1:RAMP:RATE_RBV` | read | Ramp rate from `RAMP? 1` |
| `Loop1:RANGE` | write | Heater range command |
| `Loop1:RANGE_RBV` | read | Heater range from `RANGE? 1` |
| `Loop1:HTR_RBV` | read | Heater output percentage |
| `Loop1:PID:P_RBV` | read | PID proportional readback |
| `Loop1:PID:I_RBV` | read | PID integral readback |
| `Loop1:PID:D_RBV` | read | PID derivative readback |

`Loop1:INPUT` is not writable in Phase 1. `OUTMODE? 1` returns `<mode>,<input>,<powerup enable>`; Phase 1 parses only the input field. Changing the input requires preserving the other `OUTMODE` fields and is not needed for routine remote temperature control.

### Enumerations

```text
RAMP enable:
0 = Off
1 = On

Heater range:
0 = Off
1 = Low
2 = Medium
3 = High
```

EPICS labels and instrument command integers use the same mapping.

## Command and Readback Semantics

There is no `APPLY`, `CTRL:ENABLE`, SNL program, or transaction state machine.

- Processing `Loop1:SETP` immediately sends `SETP 1,<value>`.
- Processing `Loop1:RANGE` immediately sends `RANGE 1,<value>`.
- Processing either RAMP command first queries `RAMP? 1`, preserves the other current hardware field, then sends one complete `RAMP 1,<enable>,<rate>` command.
- Every public command has a separate hardware readback.
- Command values are never copied into `_RBV` records.
- A successful `caput` means the output record completed. The corresponding `_RBV` is the only confirmation of hardware state.

### RAMP implementation

The RAMP query and write occur in one StreamDevice protocol execution:

```text
write rate:
RAMP? 1 -> store current enable in an internal soft cache
          -> RAMP 1,<cached enable>,<new rate>

write enable:
RAMP? 1 -> store current rate in an internal soft cache
          -> RAMP 1,<new enable>,<cached rate>
```

StreamDevice locks the asyn device from the first `out` until the protocol terminates, preventing another record from inserting a command between query and write. Input redirection writes the preserved field to an internal passive soft record.

The internal RAMP cache exists only for the active query-preserve-write operation. It is not a public PV, is not archived, and never updates or replaces `RAMP:ENABLE_RBV` or `RAMP:RATE_RBV`.

The first implementation task is a minimal RAMP protocol prototype that verifies:

- Query parsing into the internal cache.
- Active output-record value formatting.
- Floating-point command formatting accepted by the Model 336.
- No command interleaving on the shared asyn port.

## Polling and Startup

| Data | Scan period |
|---|---|
| A-D temperature | 2 seconds |
| Control input, setpoint, ramp, range, heater output | 2 seconds |
| PID readbacks | 10 seconds |
| IDN | 10 seconds |

Startup behavior:

- All output records use `PINI=NO`.
- IOC startup performs queries only.
- IOC startup never sends `SETP`, `RAMP`, or `RANGE`.
- An output protocol may use a read-only `@init` handler to initialize its displayed command value.
- An `@init` result does not process the output record.
- `_RBV` records remain authoritative.

## Limits and Write Failures

- Setpoint accepts 0-350 K.
- Ramp rate accepts 0-10 K/min.
- Range accepts only Off, Low, Medium, or High.
- Each numeric public command is the StreamDevice output record. Its `SDIS` link processes a passive validation record whose expression rejects values outside the closed interval exactly.
- The validation record reads the command's `VAL` through an `NPP` link, so checking `SDIS` does not recursively process the output record.
- Numeric command records use `LOPR/HOPR` as client display metadata and deliberately omit active `DRVL/DRVH` clamping.
- A valid value leaves the output record enabled. An invalid value updates the error-summary path and disables the output record before record support runs.
- Invalid numeric commands therefore produce `DISABLE/INVALID` on the public command record without calling StreamDevice device support.
- StreamDevice timeout, write, read, disconnect, or parse failures set the public output record to `SEVR=INVALID` with the corresponding `STAT`.
- Readback records retain their last value or enter their own communication alarm based on the next hardware query.

`DRVH/DRVL` alone are not a safety guard because EPICS `ao` conversion clamps an out-of-range value before downstream validation. The implementation must test both boundary values and values immediately outside each boundary and must inspect the mock serial command log.

## Communication Status

Required readbacks for overall communication status are:

- `IDN`
- Input A-D temperatures
- `Loop1:INPUT_RBV`
- `Loop1:SETP_RBV`
- RAMP enable and rate
- Heater range
- Heater output

PID readback alarms do not change overall communication status.

State rules:

- `Disconnected`: IDN has no valid communication.
- `Connected`: IDN and all required readbacks are valid.
- `Error`: IDN is valid but at least one required readback is in alarm.

After USB removal, a short `Connected -> Error -> Disconnected` transition is acceptable. No failure counters, acknowledgement, or recovery state machine are added. Normal asyn auto-connect and periodic scans provide recovery after reconnection.

## Tests and Acceptance

### Offline repository tests

- Required PV names, access direction, record types, scan periods, and enum mappings.
- `ColdHead:TEMP_RBV` and `Sample:TEMP_RBV` are aliases and do not add protocol transactions.
- Protocol commands for IDN, A-D, OUTMODE control-input readback, setpoint, RAMP, range, heater output, and PID.
- RAMP query-preserve-write protocol structure.
- Internal RAMP caches are not public readbacks.
- Output records use `PINI=NO`.
- No SNL, `APPLY`, `CTRL:ENABLE`, PID write, or control-input write.
- Numeric boundaries, `DISABLE/INVALID` alarms, error-summary updates, and absence of invalid commands in the mock serial log.
- Serial startup remains 57600 baud, 7 data bits, odd parity, one stop bit.

### IOC build checks

- EPICS Base, asyn, and StreamDevice build without adding new support modules.
- IOC executable and DBD are generated.
- Startup loads the expanded database and protocol.

### USB hardware acceptance

1. Start the IOC and confirm no control command is sent during startup.
2. Verify IDN and A-D temperatures against the controller front panel.
3. Verify control input, setpoint, RAMP, range, heater output, and PID readbacks.
4. Write a beamline-approved safe setpoint and confirm `SETP_RBV`.
5. Change RAMP rate and verify enable remains unchanged.
6. Change RAMP enable and verify rate remains unchanged.
7. Switch range through Off, Low, Medium, and High only under approved hardware conditions.
8. Verify values at 0/350 K and 0/10 K/min boundaries.
9. Verify out-of-range values do not send hardware commands.
10. Unplug USB and verify record alarms and communication status.
11. Reconnect USB and verify periodic scans recover.
12. Confirm the direct ZIP/logger is operational only after stopping the IOC.

The serial settings above come from the already validated direct-control project and must not be changed to 8N1 during IOC migration.

## Implementation Order

1. Confirm asyn USB configuration and `*IDN?`.
2. Add A-D temperature readbacks and true A/B compatibility aliases.
3. Add setpoint readback, exact limit guard, and write.
4. Add range readback and write.
5. Add heater output and control-input readbacks.
6. Add ordinary RAMP readbacks.
7. Build and verify the minimal RAMP query-preserve-write prototype.
8. Add PID readbacks.
9. Add communication status and the short `ERR` summary.
10. Test numeric boundaries and prove invalid commands never reach the mock serial log.
11. Test USB removal and automatic reconnection.
12. Run the complete hardware acceptance checklist.

## Deferred Work

Phase 1 explicitly excludes:

- Writable control input.
- PID, sensor curve, alarm, or outputs 2-4 configuration.
- SNL, grouped APPLY transactions, software interlocks, and stability logic.
- EPICS Access Security.
- EPICS CSV logging and Archiver Appliance.
- Unified Phoebus, CSS, Python, or web UI.
- Linux production deployment.
- Ethernet transport.

The next transport phase replaces `drvAsynSerialPortConfigure` with `drvAsynIPPortConfigure` for Model 336 TCP port 7777. Public PV names, database semantics, and client behavior remain unchanged.
