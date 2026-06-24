#include <cstdlib>

#include <epicsExit.h>
#include <epicsThread.h>
#include <iocsh.h>
#include <dbAccess.h>

extern "C" {
int ls336_registerRecordDeviceDriver(struct dbBase *);
}

int main(int argc, char *argv[])
{
    if (argc >= 2) {
        iocsh(argv[1]);
        epicsThreadSleep(.2);
    } else {
        ls336_registerRecordDeviceDriver(pdbbase);
    }

    iocsh(0);
    epicsExit(0);
    return 0;
}
