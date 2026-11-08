#pragma once

#include <Arduino.h>
#include <atomic>
#include <stdint.h>

enum class EndstopSource : uint8_t
{
    Disabled = 0,
    Sensor1 = 1,
    Sensor2 = 2,
};

enum class EndstopSide : uint8_t
{
    Minimum = 0,
    Maximum = 1,
};

class DebouncedEndstop
{
  public:
    DebouncedEndstop(uint8_t inputPin, uint32_t debounceMilliseconds)
        : pin(inputPin), debounceMs(debounceMilliseconds)
    {
    }

    void begin(uint32_t nowMs)
    {
        pinMode(pin, INPUT);
        const bool initial = digitalRead(pin) == HIGH;
        raw.store(initial, std::memory_order_release);
        stable.store(initial, std::memory_order_release);
        candidate = initial;
        candidateSinceMs = nowMs;
    }

    bool service(uint32_t nowMs)
    {
        const bool sampled = digitalRead(pin) == HIGH;
        raw.store(sampled, std::memory_order_release);
        if (sampled != candidate)
        {
            candidate = sampled;
            candidateSinceMs = nowMs;
            return false;
        }
        if (sampled != stable.load(std::memory_order_acquire) &&
            static_cast<uint32_t>(nowMs - candidateSinceMs) >= debounceMs)
        {
            stable.store(sampled, std::memory_order_release);
            return true;
        }
        return false;
    }

    bool isActive() const { return stable.load(std::memory_order_acquire); }
    bool rawIsActive() const { return raw.load(std::memory_order_acquire); }
    uint8_t inputPin() const { return pin; }

  private:
    uint8_t pin;
    uint32_t debounceMs;
    std::atomic<bool> raw{false};
    std::atomic<bool> stable{false};
    bool candidate = false;
    uint32_t candidateSinceMs = 0;
};

inline bool endstopBlocksDirection(bool configured, bool active, EndstopSide side, int8_t direction)
{
    if (!configured || !active || direction == 0)
        return false;
    return (side == EndstopSide::Minimum && direction < 0) ||
           (side == EndstopSide::Maximum && direction > 0);
}
