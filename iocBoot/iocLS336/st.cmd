#!../../bin/linux-x86_64/ls336

< envPaths

epicsEnvSet("STREAM_PROTOCOL_PATH", "$(TOP)/ls336App/protocol")
epicsEnvSet("PORT", "$(PORT=LS336_PORT)")
epicsEnvSet("TTY", "$(TTY=/dev/ttyUSB0)")
epicsEnvSet("PREFIX", "$(PREFIX=LS336:)")

dbLoadDatabase("../../dbd/ls336.dbd")
ls336_registerRecordDeviceDriver(pdbbase)

drvAsynSerialPortConfigure("$(PORT)", "$(TTY)", 0, 0, 0)
asynSetOption("$(PORT)", 0, "baud", "57600")
asynSetOption("$(PORT)", 0, "bits", "7")
asynSetOption("$(PORT)", 0, "parity", "odd")
asynSetOption("$(PORT)", 0, "stop", "1")
asynSetOption("$(PORT)", 0, "clocal", "Y")
asynSetOption("$(PORT)", 0, "crtscts", "N")
asynOctetSetInputEos("$(PORT)", 0, "\r\n")
asynOctetSetOutputEos("$(PORT)", 0, "\r\n")

dbLoadRecords("../../db/ls336.db", "P=$(PREFIX),PORT=$(PORT)")

iocInit()

dbl
