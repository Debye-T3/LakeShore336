TOP = .
include $(TOP)/configure/CONFIG
DIRS := configure
DIRS += ls336App
DIRS += iocBoot
include $(TOP)/configure/RULES_TOP
