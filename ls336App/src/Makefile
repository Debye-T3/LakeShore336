TOP = ../..
include $(TOP)/configure/CONFIG

PROD_IOC = ls336
DBD += ls336.dbd

ls336_DBD += base.dbd
ls336_DBD += asyn.dbd
ls336_DBD += drvAsynSerialPort.dbd
ls336_DBD += stream.dbd

ls336_SRCS += ls336Main.cpp
ls336_SRCS += ls336_registerRecordDeviceDriver.cpp

ls336_LIBS += stream
ls336_LIBS += asyn
ls336_LIBS += $(EPICS_BASE_IOC_LIBS)
ls336_SYS_LIBS_Linux += tirpc

include $(TOP)/configure/RULES
