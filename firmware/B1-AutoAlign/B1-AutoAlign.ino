/*
 * B1-AutoAlign - small ESP32 controller for a motorized polar-alignment base
 *
 * Hardware target: OpenAstroExplorer board v1 pinout
 * Control:         19200-baud Meade-style serial subset used by Ekos/INDI
 * License:         MIT (see LICENSE)
 *
 * This is a clean PA-only implementation.  It intentionally contains no
 * RA/DEC tracking, GoTo, parking, focuser, GPS, display, Wi-Fi or guiding.
 */

#include <Arduino.h>
#include <Preferences.h>
#include <atomic>
#include <esp_timer.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "EndstopInput.h"
#include "MotionAxis.h"

namespace Config
{
constexpr uint32_t SERIAL_BAUD = 19200;
constexpr size_t SERIAL_TX_BUFFER_BYTES = 512;
constexpr uint64_t MOTION_IDLE_SERVICE_US = 1000;
constexpr uint64_t MOTION_MIN_SERVICE_US = 50;

// Official OpenAstroExplorer board v1 pin map.
constexpr uint8_t ALT_STEP_PIN = 13;
constexpr uint8_t ALT_DIR_PIN  = 23;
constexpr uint8_t ALT_EN_PIN   = 4;
constexpr uint8_t AZ_STEP_PIN  = 18;
constexpr uint8_t AZ_DIR_PIN   = 19;
constexpr uint8_t AZ_EN_PIN    = 32;
constexpr uint8_t SENSOR1_PIN  = 39;
constexpr uint8_t SENSOR2_PIN  = 36;

// A4988-style enables are active low.
constexpr bool ENABLE_ACTIVE_LOW = true;

// Change one of these only if a positive command moves that axis in the
// mechanically negative direction.  The assembled base requires ALT
// inversion so positive ALT moves up and away from the physical bottom.
constexpr bool DEFAULT_ALT_DIR_INVERT = true;
constexpr bool DEFAULT_AZ_DIR_INVERT  = false;

// Conservative PA speeds.  These are step pulses at the driver input.
constexpr float ALT_MAX_SPEED = 800.0f;
constexpr float AZ_MAX_SPEED  = 800.0f;
constexpr float ALT_ACCEL     = 500.0f;
constexpr float AZ_ACCEL      = 500.0f;
constexpr float START_SPEED   = 40.0f;
constexpr uint32_t STEP_PULSE_US = 3;
constexpr uint32_t MOTION_TIMEOUT_MS = 180000;
constexpr uint32_t DEFAULT_HOLD_DELAY_MS = 5000;
constexpr uint32_t MAX_HOLD_DELAY_MS = 600000;
constexpr HoldMode DEFAULT_HOLD_MODE = HoldMode::Always;

constexpr float MAX_ALT_COMMAND_ARCMIN = 140.0f;
constexpr float MAX_AZ_COMMAND_ARCMIN = 320.0f;
constexpr int32_t MAX_RAW_JOG_STEPS = 100000;
constexpr int32_t HOME_SEARCH_STEPS = 100000;
constexpr uint32_t ENDSTOP_DEBOUNCE_MS = 5;
constexpr uint32_t CONFIG_SCHEMA_VERSION = 4;

// Migration defaults measured with the currently installed V1.13.16 setup.
// Calibrate these against real angular movement before automated alignment.
constexpr float DEFAULT_ALT_STEPS_PER_ARCMIN = 100.0f;
constexpr float DEFAULT_AZ_STEPS_PER_ARCMIN  = 11.0f;

// The present physical position was established as the ALT bottom.  On a
// fresh Preferences namespace the firmware therefore starts at ALT=0 and
// rejects all negative ALT targets.
constexpr int32_t DEFAULT_ALT_MIN = 0;
}  // namespace Config

Preferences preferences;
StepDirAxis altitude("ALT", Config::ALT_STEP_PIN, Config::ALT_DIR_PIN, Config::ALT_EN_PIN,
                     Config::DEFAULT_ALT_DIR_INVERT,
                     Config::ENABLE_ACTIVE_LOW, Config::ALT_MAX_SPEED, Config::ALT_ACCEL, Config::START_SPEED,
                     Config::STEP_PULSE_US, Config::MOTION_TIMEOUT_MS);
StepDirAxis azimuth("AZ", Config::AZ_STEP_PIN, Config::AZ_DIR_PIN, Config::AZ_EN_PIN,
                    Config::DEFAULT_AZ_DIR_INVERT,
                    Config::ENABLE_ACTIVE_LOW, Config::AZ_MAX_SPEED, Config::AZ_ACCEL, Config::START_SPEED,
                    Config::STEP_PULSE_US, Config::MOTION_TIMEOUT_MS);
DebouncedEndstop sensor1(Config::SENSOR1_PIN, Config::ENDSTOP_DEBOUNCE_MS);
DebouncedEndstop sensor2(Config::SENSOR2_PIN, Config::ENDSTOP_DEBOUNCE_MS);

float altStepsPerArcmin = Config::DEFAULT_ALT_STEPS_PER_ARCMIN;
float azStepsPerArcmin  = Config::DEFAULT_AZ_STEPS_PER_ARCMIN;
bool altMaxEnabled = false;
int32_t altMaxPosition = 0;
bool azMinEnabled = false;
bool azMaxEnabled = false;
int32_t azMaxPosition = 0;
HoldMode holdMode = Config::DEFAULT_HOLD_MODE;
uint32_t holdDelayMs = Config::DEFAULT_HOLD_DELAY_MS;
bool altDirInvert = Config::DEFAULT_ALT_DIR_INVERT;
bool azDirInvert = Config::DEFAULT_AZ_DIR_INVERT;
std::atomic<uint8_t> altEndstopSource{static_cast<uint8_t>(EndstopSource::Disabled)};
std::atomic<uint8_t> altEndstopSide{static_cast<uint8_t>(EndstopSide::Minimum)};
std::atomic<uint8_t> azEndstopSource{static_cast<uint8_t>(EndstopSource::Disabled)};
std::atomic<uint8_t> azEndstopSide{static_cast<uint8_t>(EndstopSide::Minimum)};
bool positionDirty = false;
uint32_t lastPositionChangeMs = 0;
char lastFault[32] = "NONE";

char commandBuffer[96];
size_t commandLength = 0;
bool receivingCommand = false;

enum MotionEvent : uint32_t
{
    MotionPositionChanged = 1U << 0,
    MotionAltTimedOut = 1U << 1,
    MotionAzTimedOut = 1U << 2,
    MotionTimerFailed = 1U << 3,
    MotionCompleted = 1U << 4,
    MotionAltEndstop = 1U << 5,
    MotionAzEndstop = 1U << 6,
    MotionAltHomeNotFound = 1U << 7,
    MotionAzHomeNotFound = 1U << 8,
};

enum class HomingAxis : uint8_t
{
    None = 0,
    Altitude = 1,
    Azimuth = 2,
};

esp_timer_handle_t motionTimer = nullptr;
std::atomic<uint32_t> pendingMotionEvents{0};
std::atomic<bool> motionTimerReady{false};
std::atomic<uint8_t> homingAxis{static_cast<uint8_t>(HomingAxis::None)};

void setFault(const char *fault)
{
    strncpy(lastFault, fault, sizeof(lastFault) - 1);
    lastFault[sizeof(lastFault) - 1] = '\0';
}

void markPositionDirty()
{
    positionDirty = true;
    lastPositionChangeMs = millis();
}

void persistPositions(bool force);
void persistConfiguration();

EndstopSource configuredSource(bool altitudeAxis)
{
    const uint8_t value = altitudeAxis ? altEndstopSource.load(std::memory_order_acquire) :
                                         azEndstopSource.load(std::memory_order_acquire);
    return static_cast<EndstopSource>(value);
}

EndstopSide configuredSide(bool altitudeAxis)
{
    const uint8_t value = altitudeAxis ? altEndstopSide.load(std::memory_order_acquire) :
                                         azEndstopSide.load(std::memory_order_acquire);
    return static_cast<EndstopSide>(value);
}

bool sourceIsActive(EndstopSource source)
{
    if (source == EndstopSource::Sensor1)
        return sensor1.isActive();
    if (source == EndstopSource::Sensor2)
        return sensor2.isActive();
    return false;
}

bool endstopBlocksAxis(bool altitudeAxis, int8_t direction)
{
    const EndstopSource source = configuredSource(altitudeAxis);
    return endstopBlocksDirection(source != EndstopSource::Disabled, sourceIsActive(source),
                                  configuredSide(altitudeAxis), direction);
}

bool referenceAxisAtEndstop(bool altitudeAxis);

void serviceMotionTimer(void *)
{
    const uint32_t nowUs = micros();
    const uint32_t nowMs = millis();
    sensor1.service(nowMs);
    sensor2.service(nowMs);

    const bool altBlocked = endstopBlocksAxis(true, altitude.directionOfMotion());
    const bool azBlocked = endstopBlocksAxis(false, azimuth.directionOfMotion());
    ServiceResult altResult = ServiceResult::Idle;
    ServiceResult azResult = ServiceResult::Idle;

    uint32_t events = 0;
    if (altBlocked || azBlocked)
    {
        altitude.stopNow(nowMs);
        azimuth.stopNow(nowMs);
        events |= MotionPositionChanged | MotionCompleted;
        if (altBlocked)
            events |= MotionAltEndstop;
        if (azBlocked)
            events |= MotionAzEndstop;
    }
    else
    {
        altResult = altitude.service(nowUs, nowMs);
        azResult = azimuth.service(nowUs, nowMs);
    }

    if (altResult == ServiceResult::Stepped || altResult == ServiceResult::Completed ||
        altResult == ServiceResult::TimedOut || azResult == ServiceResult::Stepped ||
        azResult == ServiceResult::Completed || azResult == ServiceResult::TimedOut)
        events |= MotionPositionChanged;
    if (altResult == ServiceResult::Completed || azResult == ServiceResult::Completed)
        events |= MotionCompleted;

    const HomingAxis activeHome = static_cast<HomingAxis>(homingAxis.load(std::memory_order_acquire));
    if (activeHome == HomingAxis::Altitude && altResult == ServiceResult::Completed)
        events |= MotionAltHomeNotFound;
    if (activeHome == HomingAxis::Azimuth && azResult == ServiceResult::Completed)
        events |= MotionAzHomeNotFound;

    if (altResult == ServiceResult::TimedOut || azResult == ServiceResult::TimedOut)
    {
        altitude.stopNow(nowMs);
        azimuth.stopNow(nowMs);
        events |= altResult == ServiceResult::TimedOut ? MotionAltTimedOut : MotionAzTimedOut;
    }

    const uint32_t deadlineUs = micros();
    const uint32_t altWaitUs = altitude.microsecondsUntilStep(deadlineUs);
    const uint32_t azWaitUs = azimuth.microsecondsUntilStep(deadlineUs);
    uint64_t nextServiceUs = Config::MOTION_IDLE_SERVICE_US;
    if (altWaitUs != UINT32_MAX || azWaitUs != UINT32_MAX)
    {
        if (altWaitUs == UINT32_MAX)
            nextServiceUs = azWaitUs;
        else if (azWaitUs == UINT32_MAX)
            nextServiceUs = altWaitUs;
        else
            nextServiceUs = altWaitUs < azWaitUs ? altWaitUs : azWaitUs;
        if (nextServiceUs < Config::MOTION_MIN_SERVICE_US)
            nextServiceUs = Config::MOTION_MIN_SERVICE_US;
    }

    if (esp_timer_restart(motionTimer, nextServiceUs) != ESP_OK)
    {
        altitude.stopNow(nowMs);
        azimuth.stopNow(nowMs);
        motionTimerReady.store(false, std::memory_order_release);
        events |= MotionPositionChanged | MotionTimerFailed;
    }
    if (events != 0)
        pendingMotionEvents.fetch_or(events, std::memory_order_release);
}

bool startMotionTimer()
{
    const esp_timer_create_args_t timerConfig = {
        .callback = serviceMotionTimer,
        .arg = nullptr,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "b1_motion",
        .skip_unhandled_events = true,
    };
    if (esp_timer_create(&timerConfig, &motionTimer) != ESP_OK)
        return false;
    if (esp_timer_start_periodic(motionTimer, Config::MOTION_IDLE_SERVICE_US) != ESP_OK)
    {
        esp_timer_delete(motionTimer);
        motionTimer = nullptr;
        return false;
    }
    motionTimerReady.store(true, std::memory_order_release);
    return true;
}

bool referenceAxisAtEndstop(bool altitudeAxis)
{
    const EndstopSide side = configuredSide(altitudeAxis);
    if (altitudeAxis)
    {
        if (side == EndstopSide::Minimum)
            altitude.setCurrentPosition(Config::DEFAULT_ALT_MIN);
        else
        {
            if (!altMaxEnabled)
                return false;
            altitude.setCurrentPosition(altMaxPosition);
        }
        altitude.setLimits(true, Config::DEFAULT_ALT_MIN, altMaxEnabled, altMaxPosition);
    }
    else
    {
        if (side == EndstopSide::Minimum)
        {
            azimuth.setCurrentPosition(0);
            azMinEnabled = true;
        }
        else
        {
            if (!azMaxEnabled)
                return false;
            azimuth.setCurrentPosition(azMaxPosition);
        }
        azimuth.setLimits(azMinEnabled, 0, azMaxEnabled, azMaxPosition);
    }
    persistConfiguration();
    markPositionDirty();
    persistPositions(true);
    return true;
}

void consumeMotionEvents()
{
    const uint32_t events = pendingMotionEvents.exchange(0, std::memory_order_acq_rel);
    if ((events & MotionPositionChanged) != 0)
        markPositionDirty();
    const HomingAxis activeHome = static_cast<HomingAxis>(homingAxis.load(std::memory_order_acquire));
    const bool altEndstopHit = (events & MotionAltEndstop) != 0;
    const bool azEndstopHit = (events & MotionAzEndstop) != 0;
    const bool altReferenced = !altEndstopHit || referenceAxisAtEndstop(true);
    const bool azReferenced = !azEndstopHit || referenceAxisAtEndstop(false);

    if (altEndstopHit || azEndstopHit || (events & (MotionAltHomeNotFound | MotionAzHomeNotFound)) != 0 ||
        (events & (MotionAltTimedOut | MotionAzTimedOut | MotionTimerFailed)) != 0)
        homingAxis.store(static_cast<uint8_t>(HomingAxis::None), std::memory_order_release);

    if ((events & MotionTimerFailed) != 0)
        setFault("MOTION_TIMER");
    else if ((events & MotionAltTimedOut) != 0)
        setFault("ALT_TIMEOUT");
    else if ((events & MotionAzTimedOut) != 0)
        setFault("AZ_TIMEOUT");
    else if ((events & MotionAltHomeNotFound) != 0)
        setFault("ALT_HOME_NOT_FOUND");
    else if ((events & MotionAzHomeNotFound) != 0)
        setFault("AZ_HOME_NOT_FOUND");
    else if (altEndstopHit && azEndstopHit)
        setFault("BOTH_ENDSTOP");
    else if (altEndstopHit)
        setFault(!altReferenced ? "ALT_ENDSTOP_UNREF" :
                 (activeHome == HomingAxis::Altitude ? "ALT_HOMED" : "ALT_ENDSTOP"));
    else if (azEndstopHit)
        setFault(!azReferenced ? "AZ_ENDSTOP_UNREF" :
                 (activeHome == HomingAxis::Azimuth ? "AZ_HOMED" : "AZ_ENDSTOP"));
    if ((events & MotionCompleted) != 0 && !altitude.isMoving() && !azimuth.isMoving())
        persistPositions(true);
}

bool motionAvailable(bool reply)
{
    if (motionTimerReady.load(std::memory_order_acquire))
        return true;
    setFault("MOTION_TIMER");
    if (reply)
        Serial.print('0');
    return false;
}

void persistPositions(bool force)
{
    if (!positionDirty && !force)
        return;
    if (altitude.isMoving() || azimuth.isMoving())
        return;
    if (!force && millis() - lastPositionChangeMs < 1500)
        return;
    preferences.putLong("altPos", altitude.position());
    preferences.putLong("azPos", azimuth.position());
    positionDirty = false;
}

void persistConfiguration()
{
    preferences.putUInt("schema", Config::CONFIG_SCHEMA_VERSION);
    preferences.putFloat("altCal", altStepsPerArcmin);
    preferences.putFloat("azCal", azStepsPerArcmin);
    preferences.putBool("altMaxEn", altMaxEnabled);
    preferences.putLong("altMax", altMaxPosition);
    preferences.putBool("azMinEn", azMinEnabled);
    preferences.putBool("azMaxEn", azMaxEnabled);
    preferences.putLong("azMax", azMaxPosition);
    preferences.putUChar("holdMode", static_cast<uint8_t>(holdMode));
    preferences.putUInt("holdDelay", holdDelayMs);
    preferences.putBool("altInv", altDirInvert);
    preferences.putBool("azInv", azDirInvert);
    preferences.putUChar("altEsSrc", altEndstopSource.load(std::memory_order_acquire));
    preferences.putUChar("altEsSide", altEndstopSide.load(std::memory_order_acquire));
    preferences.putUChar("azEsSrc", azEndstopSource.load(std::memory_order_acquire));
    preferences.putUChar("azEsSide", azEndstopSide.load(std::memory_order_acquire));
}

bool limitsReady()
{
    return altitude.hasMinimum() && altitude.hasMaximum() && azimuth.hasMinimum() && azimuth.hasMaximum();
}

void printMotionStatus()
{
    char motion[] = "------";
    if (azimuth.isMoving())
        motion[3] = azimuth.targetPosition() < azimuth.position() ? 'Z' : 'z';
    if (altitude.isMoving())
        motion[4] = altitude.targetPosition() < altitude.position() ? 'A' : 'a';
    Serial.printf("Parked,%s,0,0,0,000000,+900000,,#", motion);
}

void reportMoveResult(MoveResult result, bool returnAck)
{
    switch (result)
    {
        case MoveResult::Accepted:
            setFault("NONE");
            if (returnAck)
                Serial.print('1');
            break;
        case MoveResult::MinLimit:
            setFault("MIN_LIMIT");
            if (returnAck)
                Serial.print('0');
            break;
        case MoveResult::MaxLimit:
            setFault("MAX_LIMIT");
            if (returnAck)
                Serial.print('0');
            break;
        case MoveResult::Busy:
            setFault("BUSY");
            if (returnAck)
                Serial.print('0');
            break;
        case MoveResult::Range:
            setFault("COMMAND_RANGE");
            if (returnAck)
                Serial.print('0');
            break;
    }
}

bool parseFloatStrict(const char *text, float &value)
{
    if (text == nullptr || *text == '\0')
        return false;
    char *end = nullptr;
    value = strtof(text, &end);
    return end != text && *end == '\0' && isfinite(value);
}

bool parseLongStrict(const char *text, int32_t &value)
{
    if (text == nullptr || *text == '\0')
        return false;
    char *end = nullptr;
    errno = 0;
    const long parsed = strtol(text, &end, 10);
    if (end == text || *end != '\0' || errno == ERANGE || parsed < INT32_MIN || parsed > INT32_MAX)
        return false;
    value = static_cast<int32_t>(parsed);
    return true;
}

bool parseFloatPair(const char *text, float &first, float &second)
{
    if (text == nullptr || *text == '\0')
        return false;
    char *separator = nullptr;
    first = strtof(text, &separator);
    if (separator == text || separator == nullptr || *separator != ',' || !isfinite(first))
        return false;
    char *end = nullptr;
    second = strtof(separator + 1, &end);
    return end != separator + 1 && *end == '\0' && isfinite(second);
}

bool parseDirectionPair(const char *text, bool &altInverted, bool &azInverted)
{
    if (text == nullptr || strlen(text) != 3 || text[1] != ',' ||
        (text[0] != '0' && text[0] != '1') || (text[2] != '0' && text[2] != '1'))
        return false;
    altInverted = text[0] == '1';
    azInverted = text[2] == '1';
    return true;
}

bool parseEndstopConfiguration(const char *text, uint8_t &altSource, uint8_t &altSide,
                               uint8_t &azSource, uint8_t &azSide)
{
    if (text == nullptr || *text == '\0')
        return false;
    long values[4] = {};
    const char *cursor = text;
    for (size_t index = 0; index < 4; ++index)
    {
        char *end = nullptr;
        errno = 0;
        values[index] = strtol(cursor, &end, 10);
        if (end == cursor || errno == ERANGE)
            return false;
        if (index < 3)
        {
            if (*end != ',')
                return false;
            cursor = end + 1;
        }
        else if (*end != '\0')
            return false;
    }
    if (values[0] < 0 || values[0] > 2 || values[1] < 0 || values[1] > 1 ||
        values[2] < 0 || values[2] > 2 || values[3] < 0 || values[3] > 1 ||
        (values[0] != 0 && values[0] == values[2]))
        return false;
    altSource = static_cast<uint8_t>(values[0]);
    altSide = static_cast<uint8_t>(values[1]);
    azSource = static_cast<uint8_t>(values[2]);
    azSide = static_cast<uint8_t>(values[3]);
    return true;
}

bool arcminutesToSteps(float arcminutes, float calibration, int32_t &steps)
{
    const double requested = static_cast<double>(arcminutes) * calibration;
    if (requested < INT32_MIN || requested > INT32_MAX)
        return false;
    steps = static_cast<int32_t>(llround(requested));
    return true;
}

bool targetBlockedByEndstop(bool altitudeAxis, int32_t target)
{
    StepDirAxis &axis = altitudeAxis ? altitude : azimuth;
    const int32_t current = axis.position();
    const int8_t direction = target > current ? 1 : (target < current ? -1 : 0);
    if (!endstopBlocksAxis(altitudeAxis, direction))
        return false;
    setFault(altitudeAxis ? "ALT_ENDSTOP" : "AZ_ENDSTOP");
    return true;
}

bool startRelativeAxisMove(bool altitudeAxis, int32_t delta, bool returnAck)
{
    StepDirAxis &axis = altitudeAxis ? altitude : azimuth;
    int32_t target = axis.position();
    const MoveResult result = axis.calculateRelativeTarget(delta, target);
    if (result != MoveResult::Accepted)
    {
        reportMoveResult(result, returnAck);
        return false;
    }
    if (targetBlockedByEndstop(altitudeAxis, target))
    {
        if (returnAck)
            Serial.print('0');
        return false;
    }
    axis.startValidatedMove(target, micros(), millis());
    setFault("NONE");
    if (returnAck)
        Serial.print('1');
    return true;
}

bool startAtomicRelativeMove(int32_t azDelta, int32_t altDelta)
{
    if (!motionAvailable(false))
        return false;
    if (azDelta == 0 && altDelta == 0)
    {
        setFault("ZERO_CORRECTION");
        return false;
    }

    int32_t azTarget = azimuth.position();
    int32_t altTarget = altitude.position();
    const MoveResult azResult = azimuth.calculateRelativeTarget(azDelta, azTarget);
    const MoveResult altResult = altitude.calculateRelativeTarget(altDelta, altTarget);
    if (azResult != MoveResult::Accepted)
    {
        reportMoveResult(azResult, false);
        return false;
    }
    if (altResult != MoveResult::Accepted)
    {
        reportMoveResult(altResult, false);
        return false;
    }
    if (targetBlockedByEndstop(false, azTarget) || targetBlockedByEndstop(true, altTarget))
        return false;

    const uint32_t nowUs = micros();
    const uint32_t nowMs = millis();
    azimuth.startValidatedMove(azTarget, nowUs, nowMs);
    altitude.startValidatedMove(altTarget, nowUs, nowMs);
    setFault("NONE");
    return true;
}

bool startAtomicAbsoluteMove(int32_t azTarget, int32_t altTarget)
{
    if (!motionAvailable(false))
        return false;
    const MoveResult azResult = azimuth.validateTarget(azTarget);
    const MoveResult altResult = altitude.validateTarget(altTarget);
    if (azResult != MoveResult::Accepted)
    {
        reportMoveResult(azResult, false);
        return false;
    }
    if (altResult != MoveResult::Accepted)
    {
        reportMoveResult(altResult, false);
        return false;
    }
    if (targetBlockedByEndstop(false, azTarget) || targetBlockedByEndstop(true, altTarget))
        return false;

    const uint32_t nowUs = micros();
    const uint32_t nowMs = millis();
    azimuth.startValidatedMove(azTarget, nowUs, nowMs);
    altitude.startValidatedMove(altTarget, nowUs, nowMs);
    setFault("NONE");
    return true;
}

bool startEndstopHome(bool altitudeAxis)
{
    if (!motionAvailable(false) || altitude.isMoving() || azimuth.isMoving())
    {
        setFault(motionTimerReady.load(std::memory_order_acquire) ? "BUSY" : "MOTION_TIMER");
        return false;
    }
    const EndstopSource source = configuredSource(altitudeAxis);
    if (source == EndstopSource::Disabled)
    {
        setFault(altitudeAxis ? "ALT_ENDSTOP_OFF" : "AZ_ENDSTOP_OFF");
        return false;
    }
    const EndstopSide side = configuredSide(altitudeAxis);
    if (side == EndstopSide::Maximum &&
        ((altitudeAxis && !altMaxEnabled) || (!altitudeAxis && !azMaxEnabled)))
    {
        setFault(altitudeAxis ? "ALT_MAX_UNSET" : "AZ_MAX_UNSET");
        return false;
    }
    if (sourceIsActive(source))
    {
        if (!referenceAxisAtEndstop(altitudeAxis))
        {
            setFault(altitudeAxis ? "ALT_ENDSTOP_UNREF" : "AZ_ENDSTOP_UNREF");
            return false;
        }
        setFault(altitudeAxis ? "ALT_HOMED" : "AZ_HOMED");
        return true;
    }

    StepDirAxis &axis = altitudeAxis ? altitude : azimuth;
    const HomingAxis requestedHome = altitudeAxis ? HomingAxis::Altitude : HomingAxis::Azimuth;
    homingAxis.store(static_cast<uint8_t>(requestedHome), std::memory_order_release);
    const int8_t direction = side == EndstopSide::Minimum ? -1 : 1;
    const MoveResult result = axis.startHomingMove(direction, Config::HOME_SEARCH_STEPS, micros(), millis());
    if (result != MoveResult::Accepted)
    {
        homingAxis.store(static_cast<uint8_t>(HomingAxis::None), std::memory_order_release);
        reportMoveResult(result, false);
        return false;
    }
    setFault("NONE");
    return true;
}

void handlePaExtension(const char *body)
{
    if (strncmp(body, "PES", 3) == 0)
    {
        uint8_t requestedAltSource = 0;
        uint8_t requestedAltSide = 0;
        uint8_t requestedAzSource = 0;
        uint8_t requestedAzSide = 0;
        if (!parseEndstopConfiguration(body + 3, requestedAltSource, requestedAltSide,
                                       requestedAzSource, requestedAzSide))
        {
            setFault("BAD_ENDSTOP_CONFIG");
            Serial.print("0#");
            return;
        }
        if (altitude.isMoving() || azimuth.isMoving())
        {
            setFault("BUSY");
            Serial.print("0#");
            return;
        }
        altEndstopSource.store(requestedAltSource, std::memory_order_release);
        altEndstopSide.store(requestedAltSide, std::memory_order_release);
        azEndstopSource.store(requestedAzSource, std::memory_order_release);
        azEndstopSide.store(requestedAzSide, std::memory_order_release);
        persistConfiguration();
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PHEA") == 0)
    {
        Serial.print(startEndstopHome(true) ? "1#" : "0#");
        return;
    }
    if (strcmp(body, "PHEZ") == 0)
    {
        Serial.print(startEndstopHome(false) ? "1#" : "0#");
        return;
    }
    if (strcmp(body, "PAB") == 0)  // Mark current ALT position as bottom/zero.
    {
        if (altitude.isMoving())
        {
            setFault("BUSY");
            Serial.print("0#");
            return;
        }
        const int32_t oldPosition = altitude.position();
        altitude.setCurrentPosition(0);
        if (altMaxEnabled)
        {
            const int64_t shiftedMaximum = static_cast<int64_t>(altMaxPosition) - oldPosition;
            if (shiftedMaximum > 0 && shiftedMaximum <= INT32_MAX)
                altMaxPosition = static_cast<int32_t>(shiftedMaximum);
            else
                altMaxEnabled = false;
        }
        altitude.setLimits(true, 0, altMaxEnabled, altMaxPosition);
        persistConfiguration();
        markPositionDirty();
        persistPositions(true);
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PAT") == 0)  // Mark current ALT position as the top limit.
    {
        if (altitude.isMoving() || altitude.position() <= altitude.minimum())
        {
            setFault(altitude.isMoving() ? "BUSY" : "BAD_ALT_LIMIT");
            Serial.print("0#");
            return;
        }
        altMaxPosition = altitude.position();
        altMaxEnabled = true;
        altitude.setLimits(true, 0, true, altMaxPosition);
        persistConfiguration();
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PAU") == 0)  // Confirm current physical ALT is at the stored upper reference.
    {
        if (altitude.isMoving() || !altMaxEnabled || altMaxPosition <= Config::DEFAULT_ALT_MIN)
        {
            setFault(altitude.isMoving() ? "BUSY" : "ALT_MAX_UNSET");
            Serial.print("0#");
            return;
        }
        altitude.setCurrentPosition(altMaxPosition);
        altitude.setLimits(true, Config::DEFAULT_ALT_MIN, true, altMaxPosition);
        markPositionDirty();
        persistPositions(true);
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PCT") == 0)  // Clear only the ALT top limit.
    {
        if (altitude.isMoving())
        {
            setFault("BUSY");
            Serial.print("0#");
            return;
        }
        altMaxEnabled = false;
        altitude.setLimits(true, 0, false, 0);
        persistConfiguration();
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PZB") == 0)  // Mark current AZ position as lower limit/zero.
    {
        if (azimuth.isMoving())
        {
            setFault("BUSY");
            Serial.print("0#");
            return;
        }
        const int32_t oldPosition = azimuth.position();
        azimuth.setCurrentPosition(0);
        azMinEnabled = true;
        if (azMaxEnabled)
        {
            const int64_t shiftedMaximum = static_cast<int64_t>(azMaxPosition) - oldPosition;
            if (shiftedMaximum > 0 && shiftedMaximum <= INT32_MAX)
                azMaxPosition = static_cast<int32_t>(shiftedMaximum);
            else
                azMaxEnabled = false;
        }
        azimuth.setLimits(true, 0, azMaxEnabled, azMaxPosition);
        persistConfiguration();
        markPositionDirty();
        persistPositions(true);
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PZT") == 0)  // Mark current AZ position as upper limit.
    {
        if (azimuth.isMoving() || !azMinEnabled || azimuth.position() <= azimuth.minimum())
        {
            setFault(azimuth.isMoving() ? "BUSY" : "BAD_AZ_LIMIT");
            Serial.print("0#");
            return;
        }
        azMaxPosition = azimuth.position();
        azMaxEnabled = true;
        azimuth.setLimits(true, 0, true, azMaxPosition);
        persistConfiguration();
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PZC") == 0)  // Clear both AZ limits for supervised commissioning.
    {
        if (azimuth.isMoving())
        {
            setFault("BUSY");
            Serial.print("0#");
            return;
        }
        azMinEnabled = false;
        azMaxEnabled = false;
        azimuth.setLimits(false, 0, false, 0);
        persistConfiguration();
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PGL") == 0)
    {
        const HomingAxis activeHome = static_cast<HomingAxis>(homingAxis.load(std::memory_order_acquire));
        const char *state = activeHome == HomingAxis::Altitude ? "HOME_ALT" :
                            (activeHome == HomingAxis::Azimuth ? "HOME_AZ" :
                            (altitude.isMoving() ? (azimuth.isMoving() ? "BOTH" : "ALT") :
                            (azimuth.isMoving() ? "AZ" : "IDLE")));
        Serial.printf("AZ=%ld,ALT=%ld,AZMIN=", static_cast<long>(azimuth.position()),
                      static_cast<long>(altitude.position()));
        if (azMinEnabled)
            Serial.print('0');
        else
            Serial.print("NA");
        Serial.print(",AZMAX=");
        if (azMaxEnabled)
            Serial.print(static_cast<long>(azMaxPosition));
        else
            Serial.print("NA");
        Serial.print(",ALTMIN=0,ALTMAX=");
        if (altMaxEnabled)
            Serial.print(static_cast<long>(altMaxPosition));
        else
            Serial.print("NA");
        Serial.printf(",AZTARGET=%ld,ALTTARGET=%ld,ACAL=%.4f,ZCAL=%.4f,STATE=%s,FAULT=%s,"
                      "HOLD=%u,HOLDMS=%lu,AZEN=%u,ALTEN=%u,ALTINV=%u,AZINV=%u,"
                      "ES1=%u,ES2=%u,ALTES=%u,ALTESIDE=%u,AZES=%u,AZESIDE=%u,LIMITS=%u,SCHEMA=%lu#",
                      static_cast<long>(azimuth.targetPosition()), static_cast<long>(altitude.targetPosition()),
                      altStepsPerArcmin, azStepsPerArcmin, state, lastFault,
                      static_cast<unsigned>(holdMode), static_cast<unsigned long>(holdDelayMs),
                      azimuth.driverIsEnabled() ? 1U : 0U, altitude.driverIsEnabled() ? 1U : 0U,
                      altDirInvert ? 1U : 0U, azDirInvert ? 1U : 0U,
                      sensor1.isActive() ? 1U : 0U, sensor2.isActive() ? 1U : 0U,
                      static_cast<unsigned>(altEndstopSource.load(std::memory_order_acquire)),
                      static_cast<unsigned>(altEndstopSide.load(std::memory_order_acquire)),
                      static_cast<unsigned>(azEndstopSource.load(std::memory_order_acquire)),
                      static_cast<unsigned>(azEndstopSide.load(std::memory_order_acquire)),
                      limitsReady() ? 1U : 0U, static_cast<unsigned long>(Config::CONFIG_SCHEMA_VERSION));
        return;
    }
    if (strncmp(body, "PDI", 3) == 0)  // Store ALT,AZ direction inversion at physical lower references.
    {
        bool requestedAltInvert = false;
        bool requestedAzInvert = false;
        if (!parseDirectionPair(body + 3, requestedAltInvert, requestedAzInvert))
        {
            setFault("BAD_DIRECTION");
            Serial.print("0#");
            return;
        }
        if (altitude.isMoving() || azimuth.isMoving())
        {
            setFault("BUSY");
            Serial.print("0#");
            return;
        }

        const bool altChanged = requestedAltInvert != altDirInvert;
        const bool azChanged = requestedAzInvert != azDirInvert;
        altDirInvert = requestedAltInvert;
        azDirInvert = requestedAzInvert;
        altitude.setDirectionInverted(altDirInvert);
        azimuth.setDirectionInverted(azDirInvert);

        // A changed motor polarity invalidates the affected open-loop reference.
        // The command is only safe at that axis' physical lower boundary.
        if (altChanged)
        {
            altitude.setCurrentPosition(0);
            altMaxEnabled = false;
            altMaxPosition = 0;
            altitude.setLimits(true, 0, false, 0);
        }
        if (azChanged)
        {
            azimuth.setCurrentPosition(0);
            azMinEnabled = true;
            azMaxEnabled = false;
            azMaxPosition = 0;
            azimuth.setLimits(true, 0, false, 0);
        }

        persistConfiguration();
        if (altChanged || azChanged)
        {
            markPositionDirty();
            persistPositions(true);
        }
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strncmp(body, "PAC", 3) == 0)  // Atomic AZ,ALT correction in degrees.
    {
        float azDegrees = 0.0f;
        float altDegrees = 0.0f;
        if (!parseFloatPair(body + 3, azDegrees, altDegrees))
        {
            setFault("BAD_CORRECTION");
            Serial.print("0#");
            return;
        }
        if (!limitsReady())
        {
            setFault("LIMITS_NOT_READY");
            Serial.print("0#");
            return;
        }
        const float azArcminutes = azDegrees * 60.0f;
        const float altArcminutes = altDegrees * 60.0f;
        if (fabsf(azArcminutes) > Config::MAX_AZ_COMMAND_ARCMIN ||
            fabsf(altArcminutes) > Config::MAX_ALT_COMMAND_ARCMIN)
        {
            setFault("CORRECTION_RANGE");
            Serial.print("0#");
            return;
        }
        int32_t azSteps = 0;
        int32_t altSteps = 0;
        if (!arcminutesToSteps(azArcminutes, azStepsPerArcmin, azSteps) ||
            !arcminutesToSteps(altArcminutes, altStepsPerArcmin, altSteps))
        {
            setFault("CORRECTION_RANGE");
            Serial.print("0#");
            return;
        }
        Serial.print(startAtomicRelativeMove(azSteps, altSteps) ? "1#" : "0#");
        return;
    }
    if (strncmp(body, "PHM", 3) == 0)
    {
        int32_t mode = -1;
        if (!parseLongStrict(body + 3, mode) || mode < 0 || mode > 2)
        {
            setFault("BAD_HOLD_MODE");
            Serial.print("0#");
            return;
        }
        holdMode = static_cast<HoldMode>(mode);
        altitude.setHoldPolicy(holdMode, holdDelayMs);
        azimuth.setHoldPolicy(holdMode, holdDelayMs);
        persistConfiguration();
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strncmp(body, "PHD", 3) == 0)
    {
        int32_t delayMs = -1;
        if (!parseLongStrict(body + 3, delayMs) || delayMs < 0 ||
            static_cast<uint32_t>(delayMs) > Config::MAX_HOLD_DELAY_MS)
        {
            setFault("BAD_HOLD_DELAY");
            Serial.print("0#");
            return;
        }
        holdDelayMs = static_cast<uint32_t>(delayMs);
        altitude.setHoldPolicy(holdMode, holdDelayMs);
        azimuth.setHoldPolicy(holdMode, holdDelayMs);
        persistConfiguration();
        setFault("NONE");
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PDR") == 0)
    {
        const bool released = !altitude.isMoving() && !azimuth.isMoving();
        if (released)
        {
            altitude.releaseDriver();
            azimuth.releaseDriver();
        }
        if (!released)
            setFault("BUSY");
        else
            setFault("NONE");
        Serial.print(released ? "1#" : "0#");
        return;
    }
    if (strncmp(body, "PCAl", 4) == 0)
    {
        float value;
        if (parseFloatStrict(body + 4, value) && value > 0.0f && value < 100000.0f)
        {
            altStepsPerArcmin = value;
            persistConfiguration();
            setFault("NONE");
            Serial.print("1#");
        }
        else
        {
            setFault("BAD_ALT_CAL");
            Serial.print("0#");
        }
        return;
    }
    if (strncmp(body, "PCAz", 4) == 0)
    {
        float value;
        if (parseFloatStrict(body + 4, value) && value > 0.0f && value < 100000.0f)
        {
            azStepsPerArcmin = value;
            persistConfiguration();
            setFault("NONE");
            Serial.print("1#");
        }
        else
        {
            setFault("BAD_AZ_CAL");
            Serial.print("0#");
        }
        return;
    }
    Serial.print("0#");
}

void processCommand(const char *command)
{
    if (command[0] != ':')
        return;
    const char *body = command + 1;

    // Identification and read-only mount compatibility.
    if (strcmp(body, "GVP") == 0) { Serial.print("B1-AutoAlign#"); return; }
    if (strcmp(body, "GVN") == 0) { Serial.print("V0.3.0#"); return; }
    if (strcmp(body, "GVF") == 0) { Serial.print("B1-AutoAlign V0.3.0#"); return; }
    if (strcmp(body, "GVD") == 0) { Serial.print("Nov 2026#"); return; }
    if (strcmp(body, "GVT") == 0) { Serial.print("00:00:00#"); return; }
    if (strcmp(body, "GR") == 0)  { Serial.print("00:00:00#"); return; }
    if (strcmp(body, "GD") == 0)  { Serial.print("+90*00:00#"); return; }
    if (strcmp(body, "GL") == 0)  { Serial.print("00:00:00#"); return; }
    if (strcmp(body, "GS") == 0)  { Serial.print("00:00:00#"); return; }
    if (strcmp(body, "GC") == 0)  { Serial.print("01/01/26#"); return; }
    if (strcmp(body, "GG") == 0)  { Serial.print("+00#"); return; }
    if (strcmp(body, "Gc") == 0)  { Serial.print("24#"); return; }
    if (strcmp(body, "GM") == 0 || strcmp(body, "GN") == 0 ||
        strcmp(body, "GO") == 0 || strcmp(body, "GP") == 0)
    {
        Serial.print("B1-AutoAlign#");
        return;
    }
    if (strcmp(body, "GT") == 0)  { Serial.print("60.0#"); return; }
    if (strcmp(body, "Gt") == 0)  { Serial.print("+00*00#"); return; }
    if (strcmp(body, "Gg") == 0)  { Serial.print("000*00#"); return; }
    if (strcmp(body, "D") == 0)   { Serial.print('#'); return; }
    if (strcmp(body, "GX") == 0)  { printMotionStatus(); return; }

    // OpenAstroTech extension queries used by the patched INDI driver.
    if (strcmp(body, "XGAA") == 0)
    {
        Serial.printf("%ld|%ld#", static_cast<long>(azimuth.position()), static_cast<long>(altitude.position()));
        return;
    }
    if (strcmp(body, "XGA") == 0) { Serial.printf("%.1f#", altStepsPerArcmin * 60.0f); return; }
    if (strcmp(body, "XGZ") == 0) { Serial.printf("%.1f#", azStepsPerArcmin * 60.0f); return; }
    if (strcmp(body, "XGM") == 0)
    {
        Serial.print("ESP32,NO_RA,NO_DEC,NO_GPS,AUTO_AZ_ALT,NO_GYRO,NO_LCD,NO_FOC,ENDSW#");
        return;
    }
    if (strcmp(body, "XGMS") == 0) { Serial.print("PA,1,1|PA,1,1|#"); return; }

    // Relative PA movement.  The official MAL/MAZ commands are silent.
    if (strncmp(body, "MAL", 3) == 0)
    {
        if (!motionAvailable(false)) return;
        float arcmin;
        if (!parseFloatStrict(body + 3, arcmin)) { setFault("BAD_ALT_CMD"); return; }
        if (arcmin == 0.0f || fabsf(arcmin) > Config::MAX_ALT_COMMAND_ARCMIN)
        {
            setFault("COMMAND_RANGE");
            return;
        }
        int32_t delta = 0;
        if (!arcminutesToSteps(arcmin, altStepsPerArcmin, delta))
        {
            setFault("COMMAND_RANGE");
            return;
        }
        if (delta == 0)
        {
            setFault("ZERO_CORRECTION");
            return;
        }
        startRelativeAxisMove(true, delta, false);
        return;
    }
    if (strncmp(body, "MAZ", 3) == 0)
    {
        if (!motionAvailable(false)) return;
        float arcmin;
        if (!parseFloatStrict(body + 3, arcmin)) { setFault("BAD_AZ_CMD"); return; }
        if (arcmin == 0.0f || fabsf(arcmin) > Config::MAX_AZ_COMMAND_ARCMIN)
        {
            setFault("COMMAND_RANGE");
            return;
        }
        int32_t delta = 0;
        if (!arcminutesToSteps(arcmin, azStepsPerArcmin, delta))
        {
            setFault("COMMAND_RANGE");
            return;
        }
        if (delta == 0)
        {
            setFault("ZERO_CORRECTION");
            return;
        }
        startRelativeAxisMove(false, delta, false);
        return;
    }
    if (strncmp(body, "MXl", 3) == 0)
    {
        if (!motionAvailable(true)) return;
        int32_t steps;
        if (!parseLongStrict(body + 3, steps))
        {
            setFault("BAD_ALT_CMD");
            Serial.print('0');
            return;
        }
        if (steps == 0 || llabs(static_cast<long long>(steps)) > Config::MAX_RAW_JOG_STEPS)
        {
            setFault("COMMAND_RANGE");
            Serial.print('0');
            return;
        }
        startRelativeAxisMove(true, steps, true);
        return;
    }
    if (strncmp(body, "MXz", 3) == 0)
    {
        if (!motionAvailable(true)) return;
        int32_t steps;
        if (!parseLongStrict(body + 3, steps))
        {
            setFault("BAD_AZ_CMD");
            Serial.print('0');
            return;
        }
        if (steps == 0 || llabs(static_cast<long long>(steps)) > Config::MAX_RAW_JOG_STEPS)
        {
            setFault("COMMAND_RANGE");
            Serial.print('0');
            return;
        }
        startRelativeAxisMove(false, steps, true);
        return;
    }

    // Home/zero and stop.
    if (strcmp(body, "hZ") == 0)
    {
        if (altitude.isMoving() || azimuth.isMoving()) { Serial.print('0'); return; }
        altitude.setCurrentPosition(0);
        azimuth.setCurrentPosition(0);
        markPositionDirty();
        persistPositions(true);
        setFault("NONE");
        Serial.print('1');
        return;
    }
    if (strcmp(body, "MAA") == 0 || strcmp(body, "MAAH") == 0)
    {
        Serial.print(startAtomicAbsoluteMove(0, 0) ? '1' : '0');
        return;
    }
    if (strcmp(body, "Q") == 0)
    {
        const bool wasMoving = azimuth.isMoving() || altitude.isMoving();
        const uint32_t nowMs = millis();
        azimuth.stopNow(nowMs);
        altitude.stopNow(nowMs);
        homingAxis.store(static_cast<uint8_t>(HomingAxis::None), std::memory_order_release);
        markPositionDirty();
        persistPositions(true);
        setFault(wasMoving ? "STOPPED" : "NONE");
        return;
    }

    if (body[0] == 'P') { handlePaExtension(body); return; }

    // Accept harmless LX200 set operations so Ekos can synchronize time and
    // location without blocking.  They are intentionally not persisted.
    if (body[0] == 'S') { Serial.print('1'); return; }

    // Ignore unsupported RA/DEC/tracking/park commands.  This controller owns
    // only the polar-alignment base.
}

void serviceSerial()
{
    while (Serial.available() > 0)
    {
        const char incoming = static_cast<char>(Serial.read());
        // LX200/INDI performs its initial handshake with a raw ACK byte,
        // outside the normal colon/hash command framing.  "P" means polar.
        if (static_cast<uint8_t>(incoming) == 0x06)
        {
            receivingCommand = false;
            commandLength = 0;
            Serial.print('P');
            continue;
        }
        if (incoming == ':')
        {
            receivingCommand = true;
            commandLength = 0;
            commandBuffer[commandLength++] = incoming;
            continue;
        }
        if (!receivingCommand)
            continue;
        if (incoming == '#')
        {
            commandBuffer[commandLength] = '\0';
            receivingCommand = false;
            processCommand(commandBuffer);
            continue;
        }
        if (commandLength < sizeof(commandBuffer) - 1)
            commandBuffer[commandLength++] = incoming;
        else
        {
            receivingCommand = false;
            commandLength = 0;
            setFault("CMD_TOO_LONG");
        }
    }
}

void setup()
{
    Serial.setTxBufferSize(Config::SERIAL_TX_BUFFER_BYTES);
    Serial.begin(Config::SERIAL_BAUD);

    preferences.begin("b1autoalign", false);
    const uint32_t storedSchema = preferences.getUInt("schema", 0);
    const bool directionSchemaMigration = storedSchema > 0 && storedSchema < 3;
    bool configurationRepaired = false;

    altStepsPerArcmin = preferences.getFloat("altCal", Config::DEFAULT_ALT_STEPS_PER_ARCMIN);
    azStepsPerArcmin = preferences.getFloat("azCal", Config::DEFAULT_AZ_STEPS_PER_ARCMIN);
    if (!isfinite(altStepsPerArcmin) || altStepsPerArcmin <= 0.0f || altStepsPerArcmin >= 100000.0f)
    {
        altStepsPerArcmin = Config::DEFAULT_ALT_STEPS_PER_ARCMIN;
        configurationRepaired = true;
    }
    if (!isfinite(azStepsPerArcmin) || azStepsPerArcmin <= 0.0f || azStepsPerArcmin >= 100000.0f)
    {
        azStepsPerArcmin = Config::DEFAULT_AZ_STEPS_PER_ARCMIN;
        configurationRepaired = true;
    }

    altMaxEnabled = preferences.getBool("altMaxEn", false);
    altMaxPosition = preferences.getLong("altMax", 0);
    if (altMaxEnabled && altMaxPosition <= Config::DEFAULT_ALT_MIN)
    {
        altMaxEnabled = false;
        altMaxPosition = 0;
        configurationRepaired = true;
    }
    azMinEnabled = preferences.getBool("azMinEn", false);
    azMaxEnabled = preferences.getBool("azMaxEn", false);
    azMaxPosition = preferences.getLong("azMax", 0);
    if (azMaxEnabled && (!azMinEnabled || azMaxPosition <= 0))
    {
        azMaxEnabled = false;
        azMaxPosition = 0;
        configurationRepaired = true;
    }

    const uint8_t storedHoldMode = preferences.getUChar("holdMode", static_cast<uint8_t>(Config::DEFAULT_HOLD_MODE));
    if (storedHoldMode <= static_cast<uint8_t>(HoldMode::Always))
        holdMode = static_cast<HoldMode>(storedHoldMode);
    else
    {
        holdMode = Config::DEFAULT_HOLD_MODE;
        configurationRepaired = true;
    }
    holdDelayMs = preferences.getUInt("holdDelay", Config::DEFAULT_HOLD_DELAY_MS);
    if (holdDelayMs > Config::MAX_HOLD_DELAY_MS)
    {
        holdDelayMs = Config::DEFAULT_HOLD_DELAY_MS;
        configurationRepaired = true;
    }
    altDirInvert = preferences.getBool("altInv", Config::DEFAULT_ALT_DIR_INVERT);
    azDirInvert = preferences.getBool("azInv", Config::DEFAULT_AZ_DIR_INVERT);
    uint8_t storedAltEndstopSource = preferences.getUChar("altEsSrc", 0);
    uint8_t storedAltEndstopSide = preferences.getUChar("altEsSide", 0);
    uint8_t storedAzEndstopSource = preferences.getUChar("azEsSrc", 0);
    uint8_t storedAzEndstopSide = preferences.getUChar("azEsSide", 0);
    if (storedAltEndstopSource > 2 || storedAltEndstopSide > 1 ||
        storedAzEndstopSource > 2 || storedAzEndstopSide > 1 ||
        (storedAltEndstopSource != 0 && storedAltEndstopSource == storedAzEndstopSource))
    {
        storedAltEndstopSource = 0;
        storedAltEndstopSide = 0;
        storedAzEndstopSource = 0;
        storedAzEndstopSide = 0;
        configurationRepaired = true;
    }
    altEndstopSource.store(storedAltEndstopSource, std::memory_order_release);
    altEndstopSide.store(storedAltEndstopSide, std::memory_order_release);
    azEndstopSource.store(storedAzEndstopSource, std::memory_order_release);
    azEndstopSide.store(storedAzEndstopSide, std::memory_order_release);

    int32_t savedAlt = preferences.getLong("altPos", Config::DEFAULT_ALT_MIN);
    int32_t savedAz = preferences.getLong("azPos", 0);
    if (directionSchemaMigration)
    {
        // Schema 3 changes the assembled-base ALT default. The documented
        // upgrade procedure places ALT at the physical bottom before boot.
        savedAlt = Config::DEFAULT_ALT_MIN;
        altMaxEnabled = false;
        altMaxPosition = 0;
        configurationRepaired = true;
    }
    if (savedAlt < Config::DEFAULT_ALT_MIN)
    {
        savedAlt = Config::DEFAULT_ALT_MIN;
        configurationRepaired = true;
    }
    if (altMaxEnabled && savedAlt > altMaxPosition)
    {
        altMaxEnabled = false;
        altMaxPosition = 0;
        configurationRepaired = true;
    }
    if ((azMinEnabled && savedAz < 0) || (azMaxEnabled && savedAz > azMaxPosition))
    {
        azMinEnabled = false;
        azMaxEnabled = false;
        azMaxPosition = 0;
        configurationRepaired = true;
    }

    altitude.begin(savedAlt);
    azimuth.begin(savedAz);
    altitude.setDirectionInverted(altDirInvert);
    azimuth.setDirectionInverted(azDirInvert);
    altitude.setLimits(true, Config::DEFAULT_ALT_MIN, altMaxEnabled, altMaxPosition);
    azimuth.setLimits(azMinEnabled, 0, azMaxEnabled, azMaxPosition);
    altitude.setHoldPolicy(holdMode, holdDelayMs);
    azimuth.setHoldPolicy(holdMode, holdDelayMs);
    sensor1.begin(millis());
    sensor2.begin(millis());

    if (storedSchema != Config::CONFIG_SCHEMA_VERSION || configurationRepaired)
    {
        persistConfiguration();
        if (configurationRepaired)
        {
            markPositionDirty();
            persistPositions(true);
            setFault("CONFIG_REPAIRED");
        }
        else
            setFault("CONFIG_MIGRATED");
    }

    if (!startMotionTimer())
        setFault("MOTION_TIMER");
}

void loop()
{
    serviceSerial();
    consumeMotionEvents();
    persistPositions(false);
    delay(0);
}


