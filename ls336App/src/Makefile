TOP = ../..
include $(TOP)/configure/CONFIG

PROD_IOC = ls336
DBD += ls336.dbd

ls336_DBD += base.dbd
ls336_DBD += asyn.dbd
ls336_DBD += stream.dbd

ls336_SRCS += ls336_registerRecordDeviceDriver.cpp

ls336_LIBS += stream
ls336_LIBS += asyn
ls336_LIBS += $(EPICS_BASE_IOC_LIBS)

include $(TOP)/configure/RULES
