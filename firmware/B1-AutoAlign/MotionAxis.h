#pragma once

#include <Arduino.h>
#include <math.h>
#include <stdint.h>

#if defined(ARDUINO_ARCH_ESP32)
#include <freertos/FreeRTOS.h>
#include <freertos/portmacro.h>

using AxisMutex = portMUX_TYPE;
#define B1_AXIS_MUTEX_INITIALIZER portMUX_INITIALIZER_UNLOCKED

class AxisLockGuard
{
  public:
    explicit AxisLockGuard(AxisMutex &mutex) : lock(mutex) { portENTER_CRITICAL(&lock); }
    ~AxisLockGuard() { portEXIT_CRITICAL(&lock); }

  private:
    AxisMutex &lock;
};
#else
struct AxisMutex
{
};
#define B1_AXIS_MUTEX_INITIALIZER {}

class AxisLockGuard
{
  public:
    explicit AxisLockGuard(AxisMutex &) {}
};
#endif

enum class MoveResult : uint8_t
{
    Accepted,
    MinLimit,
    MaxLimit,
    Busy,
    Range
};

enum class HoldMode : uint8_t
{
    Release = 0,
    Timed = 1,
    Always = 2
};

enum class ServiceResult : uint8_t
{
    Idle,
    Stepped,
    Completed,
    TimedOut
};

class StepDirAxis
{
  public:
    StepDirAxis(const char *axisName, uint8_t stepPin, uint8_t dirPin, uint8_t enablePin, bool invertDirection,
                bool enableActiveLow, float maxStepRate, float acceleration, float startStepRate,
                uint32_t stepPulseUs, uint32_t motionTimeoutMs)
        : name(axisName), step(stepPin), dir(dirPin), enable(enablePin), invertDir(invertDirection),
          activeLowEnable(enableActiveLow), maxSpeed(maxStepRate), accel(acceleration), startSpeed(startStepRate),
          pulseUs(stepPulseUs), timeoutMs(motionTimeoutMs)
    {
    }

    void begin(int32_t savedPosition)
    {
        AxisLockGuard guard(mutex);
        pinMode(step, OUTPUT);
        pinMode(dir, OUTPUT);
        pinMode(enable, OUTPUT);
        digitalWrite(step, LOW);
        setDriverEnabledUnlocked(false);
        current = savedPosition;
        target = savedPosition;
    }

    void setLimits(bool minimumEnabled, int32_t minimum, bool maximumEnabled, int32_t maximum)
    {
        AxisLockGuard guard(mutex);
        minEnabled = minimumEnabled;
        minPosition = minimum;
        maxEnabled = maximumEnabled;
        maxPosition = maximum;
    }

    void setHoldPolicy(HoldMode mode, uint32_t delayMs)
    {
        AxisLockGuard guard(mutex);
        holdMode = mode;
        holdDelayMs = delayMs;
        if (!isMovingUnlocked())
            applyIdleHoldUnlocked(millis());
    }

    void setDirectionInverted(bool inverted)
    {
        AxisLockGuard guard(mutex);
        invertDir = inverted;
    }

    MoveResult validateTarget(int32_t requested) const
    {
        AxisLockGuard guard(mutex);
        return validateTargetUnlocked(requested);
    }

    MoveResult calculateRelativeTarget(int32_t delta, int32_t &requested) const
    {
        AxisLockGuard guard(mutex);
        return calculateRelativeTargetUnlocked(delta, requested);
    }

    void startValidatedMove(int32_t requested, uint32_t nowUs, uint32_t nowMs)
    {
        AxisLockGuard guard(mutex);
        startValidatedMoveUnlocked(requested, nowUs, nowMs);
    }

    MoveResult moveTo(int32_t requested, uint32_t nowUs, uint32_t nowMs)
    {
        AxisLockGuard guard(mutex);
        const MoveResult result = validateTargetUnlocked(requested);
        if (result == MoveResult::Accepted)
            startValidatedMoveUnlocked(requested, nowUs, nowMs);
        return result;
    }

    MoveResult moveBy(int32_t delta, uint32_t nowUs, uint32_t nowMs)
    {
        AxisLockGuard guard(mutex);
        int32_t requested = 0;
        const MoveResult result = calculateRelativeTargetUnlocked(delta, requested);
        if (result == MoveResult::Accepted)
            startValidatedMoveUnlocked(requested, nowUs, nowMs);
        return result;
    }

    void stopNow(uint32_t nowMs)
    {
        AxisLockGuard guard(mutex);
        stopNowUnlocked(nowMs);
    }

    bool releaseDriver()
    {
        AxisLockGuard guard(mutex);
        if (isMovingUnlocked())
            return false;
        setDriverEnabledUnlocked(false);
        return true;
    }

    void setCurrentPosition(int32_t value)
    {
        AxisLockGuard guard(mutex);
        current = value;
        target = value;
        speed = 0.0f;
        lastMotionMs = millis();
        applyIdleHoldUnlocked(lastMotionMs);
    }

    ServiceResult service(uint32_t nowUs, uint32_t nowMs)
    {
        AxisLockGuard guard(mutex);
        if (!isMovingUnlocked())
        {
            applyIdleHoldUnlocked(nowMs);
            return ServiceResult::Idle;
        }

        if (static_cast<uint32_t>(nowMs - motionStartedMs) >= timeoutMs)
        {
            stopNowUnlocked(nowMs);
            return ServiceResult::TimedOut;
        }

        const int64_t remaining = static_cast<int64_t>(target) - current;
        const uint32_t interval = static_cast<uint32_t>(1000000.0f / fmaxf(speed, startSpeed));
        if (static_cast<uint32_t>(nowUs - lastStepUs) < interval)
            return ServiceResult::Idle;

        const int8_t sign = remaining > 0 ? 1 : -1;
        const bool directionLevel = (sign > 0) ^ invertDir;
        digitalWrite(dir, directionLevel ? HIGH : LOW);
        digitalWrite(step, HIGH);
        delayMicroseconds(pulseUs);
        digitalWrite(step, LOW);

        current += sign;
        lastStepUs = nowUs;
        lastMotionMs = nowMs;

        const uint64_t left = static_cast<uint64_t>(remaining > 0 ? remaining - 1 : -remaining - 1);
        const float stoppingSteps = (speed * speed) / (2.0f * accel);
        if (left == 0)
        {
            speed = 0.0f;
            applyIdleHoldUnlocked(nowMs);
            return ServiceResult::Completed;
        }
        if (static_cast<float>(left) <= stoppingSteps)
            speed = sqrtf(fmaxf(startSpeed * startSpeed, speed * speed - 2.0f * accel));
        else
            speed = fminf(maxSpeed, sqrtf(speed * speed + 2.0f * accel));
        return ServiceResult::Stepped;
    }

    uint32_t microsecondsUntilStep(uint32_t nowUs) const
    {
        AxisLockGuard guard(mutex);
        if (!isMovingUnlocked())
            return UINT32_MAX;
        const uint32_t interval = static_cast<uint32_t>(1000000.0f / fmaxf(speed, startSpeed));
        const uint32_t elapsed = static_cast<uint32_t>(nowUs - lastStepUs);
        return elapsed >= interval ? 0U : interval - elapsed;
    }

    bool isMoving() const
    {
        AxisLockGuard guard(mutex);
        return isMovingUnlocked();
    }
    bool driverIsEnabled() const
    {
        AxisLockGuard guard(mutex);
        return driverEnabled;
    }
    int32_t position() const
    {
        AxisLockGuard guard(mutex);
        return current;
    }
    int32_t targetPosition() const
    {
        AxisLockGuard guard(mutex);
        return target;
    }
    int32_t minimum() const
    {
        AxisLockGuard guard(mutex);
        return minPosition;
    }
    int32_t maximum() const
    {
        AxisLockGuard guard(mutex);
        return maxPosition;
    }
    bool hasMinimum() const
    {
        AxisLockGuard guard(mutex);
        return minEnabled;
    }
    bool hasMaximum() const
    {
        AxisLockGuard guard(mutex);
        return maxEnabled;
    }
    HoldMode currentHoldMode() const
    {
        AxisLockGuard guard(mutex);
        return holdMode;
    }
    uint32_t currentHoldDelayMs() const
    {
        AxisLockGuard guard(mutex);
        return holdDelayMs;
    }
    bool directionIsInverted() const
    {
        AxisLockGuard guard(mutex);
        return invertDir;
    }
    const char *axisName() const { return name; }

  private:
    bool isMovingUnlocked() const { return current != target; }

    MoveResult validateTargetUnlocked(int32_t requested) const
    {
        if (isMovingUnlocked())
            return MoveResult::Busy;
        if (minEnabled && requested < minPosition)
            return MoveResult::MinLimit;
        if (maxEnabled && requested > maxPosition)
            return MoveResult::MaxLimit;
        return MoveResult::Accepted;
    }

    MoveResult calculateRelativeTargetUnlocked(int32_t delta, int32_t &requested) const
    {
        const int64_t wideTarget = static_cast<int64_t>(current) + delta;
        if (wideTarget < INT32_MIN || wideTarget > INT32_MAX)
            return MoveResult::Range;
        requested = static_cast<int32_t>(wideTarget);
        return validateTargetUnlocked(requested);
    }

    void startValidatedMoveUnlocked(int32_t requested, uint32_t nowUs, uint32_t nowMs)
    {
        target = requested;
        if (target != current)
        {
            speed = startSpeed;
            lastStepUs = nowUs;
            motionStartedMs = nowMs;
            setDriverEnabledUnlocked(true);
        }
    }

    void stopNowUnlocked(uint32_t nowMs)
    {
        target = current;
        speed = 0.0f;
        lastMotionMs = nowMs;
        applyIdleHoldUnlocked(nowMs);
    }

    void applyIdleHoldUnlocked(uint32_t nowMs)
    {
        if (!driverEnabled)
            return;
        if (holdMode == HoldMode::Release ||
            (holdMode == HoldMode::Timed && static_cast<uint32_t>(nowMs - lastMotionMs) >= holdDelayMs))
            setDriverEnabledUnlocked(false);
    }

    void setDriverEnabledUnlocked(bool on)
    {
        driverEnabled = on;
        const bool outputLevel = activeLowEnable ? !on : on;
        digitalWrite(enable, outputLevel ? HIGH : LOW);
    }

    const char *name;
    uint8_t step;
    uint8_t dir;
    uint8_t enable;
    bool invertDir;
    bool activeLowEnable;
    float maxSpeed;
    float accel;
    float startSpeed;
    uint32_t pulseUs;
    uint32_t timeoutMs;
    float speed = 0.0f;
    int32_t current = 0;
    int32_t target = 0;
    int32_t minPosition = 0;
    int32_t maxPosition = 0;
    bool minEnabled = false;
    bool maxEnabled = false;
    bool driverEnabled = false;
    HoldMode holdMode = HoldMode::Always;
    uint32_t holdDelayMs = 5000;
    uint32_t lastStepUs = 0;
    uint32_t lastMotionMs = 0;
    uint32_t motionStartedMs = 0;
    mutable AxisMutex mutex = B1_AXIS_MUTEX_INITIALIZER;
};

#undef B1_AXIS_MUTEX_INITIALIZER
