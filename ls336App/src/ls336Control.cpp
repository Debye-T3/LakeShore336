#include <aSubRecord.h>
#include <epicsExport.h>
#include <epicsTypes.h>

#include <cmath>
#include <cstring>

namespace {

constexpr epicsInt32 kBusy = 1;
constexpr epicsInt32 kDone = 2;
constexpr epicsInt32 kPartialFailure = 3;
constexpr epicsInt32 kError = 4;
constexpr epicsFloat64 kReadbackTolerance = 0.001;
constexpr unsigned int kErrorTextBytes = 40;

void copyError(void *destination, const char *message)
{
    if (destination == nullptr) {
        return;
    }
    auto *text = static_cast<char *>(destination);
    std::strncpy(text, message, kErrorTextBytes - 1);
    text[kErrorTextBytes - 1] = '\0';
}

bool controlValuesValid(epicsFloat64 input, epicsFloat64 setpoint,
                        epicsFloat64 rampRate, epicsFloat64 range)
{
    return std::isfinite(input) && input >= 1 && input <= 4 &&
           std::floor(input) == input && std::isfinite(setpoint) &&
           setpoint >= 0.0 && setpoint <= 350.0 &&
           std::isfinite(rampRate) && rampRate >= 0.0 && rampRate <= 10.0 &&
           std::isfinite(range) && range >= 0.0 && range <= 3.0 &&
           std::floor(range) == range;
}

bool pidValuesValid(epicsFloat64 p, epicsFloat64 i, epicsFloat64 d)
{
    return std::isfinite(p) && p >= 0.1 && p <= 1000.0 &&
           std::isfinite(i) && i >= 0.1 && i <= 1000.0 &&
           std::isfinite(d) && d >= 0.0 && d <= 200.0;
}

} // namespace

long ls336PrepareControlApply(aSubRecord *record)
{
    if (record == nullptr || record->a == nullptr || record->b == nullptr ||
        record->c == nullptr || record->d == nullptr || record->vala == nullptr ||
        record->valb == nullptr || record->valc == nullptr || record->vald == nullptr ||
        record->vale == nullptr || record->valf == nullptr || record->valg == nullptr ||
        record->valh == nullptr || record->vali == nullptr) {
        return -1;
    }

    const auto input = *static_cast<epicsFloat64 *>(record->a);
    const auto setpoint = *static_cast<epicsFloat64 *>(record->b);
    const auto rampRate = *static_cast<epicsFloat64 *>(record->c);
    const auto range = *static_cast<epicsFloat64 *>(record->d);
    const bool valid = controlValuesValid(input, setpoint, rampRate, range);

    *static_cast<epicsEnum16 *>(record->vala) = valid ? static_cast<epicsEnum16>(input) : 0;
    *static_cast<epicsFloat64 *>(record->valb) = setpoint;
    *static_cast<epicsFloat64 *>(record->valc) = rampRate;
    *static_cast<epicsEnum16 *>(record->vald) = valid ? static_cast<epicsEnum16>(range) : 0;
    *static_cast<epicsInt32 *>(record->vale) = valid ? 1 : 0;
    *static_cast<epicsInt32 *>(record->valf) = valid ? kBusy : kError;
    *static_cast<epicsInt32 *>(record->valg) = valid ? 1 : 0;
    *static_cast<epicsInt32 *>(record->vali) = rampRate > 0.0 ? 1 : 0;
    record->neva = 1;
    record->nevb = 1;
    record->nevc = 1;
    record->nevd = 1;
    record->neve = 1;
    record->nevf = 1;
    record->nevg = 1;
    record->nevh = 1;
    record->nevi = 1;

    const char *message = "";
    if (!std::isfinite(input) || input < 1 || input > 4 || std::floor(input) != input) {
        message = "Input must be integer A-D code 1..4";
    } else if (!std::isfinite(setpoint) || setpoint < 0.0 || setpoint > 350.0) {
        message = "Setpoint must be 0..350 K";
    } else if (!std::isfinite(rampRate) || rampRate < 0.0 || rampRate > 10.0) {
        message = "Ramp rate must be 0..10 K/min";
    } else if (!std::isfinite(range) || range < 0 || range > 3 || std::floor(range) != range) {
        message = "Heater range must be integer 0..3";
    }
    copyError(record->valh, message);
    return 0;
}

long ls336FinishControlApply(aSubRecord *record)
{
    if (record == nullptr || record->a == nullptr || record->b == nullptr ||
        record->c == nullptr || record->d == nullptr || record->e == nullptr ||
        record->f == nullptr || record->g == nullptr || record->h == nullptr ||
        record->i == nullptr || record->j == nullptr || record->vala == nullptr ||
        record->k == nullptr || record->valb == nullptr || record->valc == nullptr) {
        return -1;
    }

    if (*static_cast<epicsInt32 *>(record->k) == 0) {
        record->neva = 0;
        record->nevb = 0;
        record->nevc = 0;
        return 0;
    }

    const auto commandSeverity = *static_cast<epicsEnum16 *>(record->a);
    const auto requestedSetpoint = *static_cast<epicsFloat64 *>(record->b);
    const auto requestedRamp = *static_cast<epicsFloat64 *>(record->c);
    const auto requestedRange = *static_cast<epicsEnum16 *>(record->d);
    const auto requestedInput = *static_cast<epicsEnum16 *>(record->e);
    const auto actualSetpoint = *static_cast<epicsFloat64 *>(record->f);
    const auto actualRampEnable = *static_cast<epicsEnum16 *>(record->g);
    const auto actualRampRate = *static_cast<epicsFloat64 *>(record->h);
    const auto actualRange = *static_cast<epicsEnum16 *>(record->i);
    const auto actualInput = *static_cast<epicsEnum16 *>(record->j);

    const bool matches = std::isfinite(actualSetpoint) &&
                         std::fabs(actualSetpoint - requestedSetpoint) <= kReadbackTolerance &&
                         actualRampEnable == (requestedRamp > 0.0 ? 1 : 0) &&
                         std::isfinite(actualRampRate) &&
                         std::fabs(actualRampRate - requestedRamp) <= kReadbackTolerance &&
                         actualRange == requestedRange && actualInput == requestedInput;

    const epicsInt32 status = commandSeverity != 0 ? kError :
                              (matches ? kDone : kPartialFailure);
    *static_cast<epicsInt32 *>(record->vala) = status;
    *static_cast<epicsInt32 *>(record->valb) = 0;
    copyError(record->valc, commandSeverity != 0 ? "APPLY protocol failed" :
              (matches ? "" : "Readback differs from request"));
    record->neva = 1;
    record->nevb = 1;
    record->nevc = 1;
    return 0;
}

long ls336PreparePidApply(aSubRecord *record)
{
    if (record == nullptr || record->a == nullptr || record->b == nullptr ||
        record->c == nullptr || record->vala == nullptr || record->valb == nullptr ||
        record->valc == nullptr || record->vald == nullptr || record->vale == nullptr ||
        record->valf == nullptr || record->valg == nullptr) {
        return -1;
    }

    const auto p = *static_cast<epicsFloat64 *>(record->a);
    const auto i = *static_cast<epicsFloat64 *>(record->b);
    const auto d = *static_cast<epicsFloat64 *>(record->c);
    const bool valid = pidValuesValid(p, i, d);

    *static_cast<epicsFloat64 *>(record->vala) = p;
    *static_cast<epicsFloat64 *>(record->valb) = i;
    *static_cast<epicsFloat64 *>(record->valc) = d;
    *static_cast<epicsInt32 *>(record->vald) = valid ? 1 : 0;
    *static_cast<epicsInt32 *>(record->vale) = valid ? kBusy : kError;
    *static_cast<epicsInt32 *>(record->valf) = valid ? 1 : 0;
    copyError(record->valg, valid ? "" : "PID values out of range");
    record->neva = 1;
    record->nevb = 1;
    record->nevc = 1;
    record->nevd = 1;
    record->neve = 1;
    record->nevf = 1;
    record->nevg = 1;
    return 0;
}

long ls336FinishPidApply(aSubRecord *record)
{
    if (record == nullptr || record->a == nullptr || record->b == nullptr ||
        record->c == nullptr || record->d == nullptr || record->e == nullptr ||
        record->f == nullptr || record->g == nullptr || record->vala == nullptr ||
        record->h == nullptr || record->valb == nullptr || record->valc == nullptr) {
        return -1;
    }

    if (*static_cast<epicsInt32 *>(record->h) == 0) {
        record->neva = 0;
        record->nevb = 0;
        record->nevc = 0;
        return 0;
    }

    const auto commandSeverity = *static_cast<epicsEnum16 *>(record->a);
    const auto requestedP = *static_cast<epicsFloat64 *>(record->b);
    const auto requestedI = *static_cast<epicsFloat64 *>(record->c);
    const auto requestedD = *static_cast<epicsFloat64 *>(record->d);
    const auto actualP = *static_cast<epicsFloat64 *>(record->e);
    const auto actualI = *static_cast<epicsFloat64 *>(record->f);
    const auto actualD = *static_cast<epicsFloat64 *>(record->g);
    const bool matches = std::isfinite(actualP) && std::isfinite(actualI) &&
                         std::isfinite(actualD) &&
                         std::fabs(actualP - requestedP) <= kReadbackTolerance &&
                         std::fabs(actualI - requestedI) <= kReadbackTolerance &&
                         std::fabs(actualD - requestedD) <= kReadbackTolerance;

    *static_cast<epicsInt32 *>(record->vala) = commandSeverity != 0 ? kError :
                                               (matches ? kDone : kError);
    *static_cast<epicsInt32 *>(record->valb) = 0;
    copyError(record->valc, commandSeverity != 0 ? "PID protocol failed" :
              (matches ? "" : "PID readback differs"));
    record->neva = 1;
    record->nevb = 1;
    record->nevc = 1;
    return 0;
}

epicsRegisterFunction(ls336PrepareControlApply);
epicsRegisterFunction(ls336FinishControlApply);
epicsRegisterFunction(ls336PreparePidApply);
epicsRegisterFunction(ls336FinishPidApply);
