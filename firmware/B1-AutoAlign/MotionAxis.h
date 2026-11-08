#pragma once

#include <Arduino.h>
#include <math.h>
#include <stdint.h>

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
        pinMode(step, OUTPUT);
        pinMode(dir, OUTPUT);
        pinMode(enable, OUTPUT);
        digitalWrite(step, LOW);
        setDriverEnabled(false);
        current = savedPosition;
        target = savedPosition;
    }

    void setLimits(bool minimumEnabled, int32_t minimum, bool maximumEnabled, int32_t maximum)
    {
        minEnabled = minimumEnabled;
        minPosition = minimum;
        maxEnabled = maximumEnabled;
        maxPosition = maximum;
    }

    void setHoldPolicy(HoldMode mode, uint32_t delayMs)
    {
        holdMode = mode;
        holdDelayMs = delayMs;
        if (!isMoving())
            applyIdleHold(millis());
    }

    void setDirectionInverted(bool inverted)
    {
        invertDir = inverted;
    }

    MoveResult validateTarget(int32_t requested) const
    {
        if (isMoving())
            return MoveResult::Busy;
        if (minEnabled && requested < minPosition)
            return MoveResult::MinLimit;
        if (maxEnabled && requested > maxPosition)
            return MoveResult::MaxLimit;
        return MoveResult::Accepted;
    }

    MoveResult calculateRelativeTarget(int32_t delta, int32_t &requested) const
    {
        const int64_t wideTarget = static_cast<int64_t>(current) + delta;
        if (wideTarget < INT32_MIN || wideTarget > INT32_MAX)
            return MoveResult::Range;
        requested = static_cast<int32_t>(wideTarget);
        return validateTarget(requested);
    }

    void startValidatedMove(int32_t requested, uint32_t nowUs, uint32_t nowMs)
    {
        target = requested;
        if (target != current)
        {
            speed = startSpeed;
            lastStepUs = nowUs;
            motionStartedMs = nowMs;
            setDriverEnabled(true);
        }
    }

    MoveResult moveTo(int32_t requested, uint32_t nowUs, uint32_t nowMs)
    {
        const MoveResult result = validateTarget(requested);
        if (result == MoveResult::Accepted)
            startValidatedMove(requested, nowUs, nowMs);
        return result;
    }

    MoveResult moveBy(int32_t delta, uint32_t nowUs, uint32_t nowMs)
    {
        int32_t requested = 0;
        const MoveResult result = calculateRelativeTarget(delta, requested);
        if (result == MoveResult::Accepted)
            startValidatedMove(requested, nowUs, nowMs);
        return result;
    }

    void stopNow(uint32_t nowMs)
    {
        target = current;
        speed = 0.0f;
        lastMotionMs = nowMs;
        applyIdleHold(nowMs);
    }

    bool releaseDriver()
    {
        if (isMoving())
            return false;
        setDriverEnabled(false);
        return true;
    }

    void setCurrentPosition(int32_t value)
    {
        current = value;
        target = value;
        speed = 0.0f;
        lastMotionMs = millis();
        applyIdleHold(lastMotionMs);
    }

    ServiceResult service(uint32_t nowUs, uint32_t nowMs)
    {
        if (!isMoving())
        {
            applyIdleHold(nowMs);
            return ServiceResult::Idle;
        }

        if (static_cast<uint32_t>(nowMs - motionStartedMs) >= timeoutMs)
        {
            stopNow(nowMs);
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
            applyIdleHold(nowMs);
            return ServiceResult::Completed;
        }
        if (static_cast<float>(left) <= stoppingSteps)
            speed = sqrtf(fmaxf(startSpeed * startSpeed, speed * speed - 2.0f * accel));
        else
            speed = fminf(maxSpeed, sqrtf(speed * speed + 2.0f * accel));
        return ServiceResult::Stepped;
    }

    bool isMoving() const { return current != target; }
    bool driverIsEnabled() const { return driverEnabled; }
    int32_t position() const { return current; }
    int32_t targetPosition() const { return target; }
    int32_t minimum() const { return minPosition; }
    int32_t maximum() const { return maxPosition; }
    bool hasMinimum() const { return minEnabled; }
    bool hasMaximum() const { return maxEnabled; }
    HoldMode currentHoldMode() const { return holdMode; }
    uint32_t currentHoldDelayMs() const { return holdDelayMs; }
    bool directionIsInverted() const { return invertDir; }
    const char *axisName() const { return name; }

  private:
    void applyIdleHold(uint32_t nowMs)
    {
        if (!driverEnabled)
            return;
        if (holdMode == HoldMode::Release ||
            (holdMode == HoldMode::Timed && static_cast<uint32_t>(nowMs - lastMotionMs) >= holdDelayMs))
            setDriverEnabled(false);
    }

    void setDriverEnabled(bool on)
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
};
