#pragma once

#include <stdint.h>

constexpr uint8_t OUTPUT = 1;
constexpr uint8_t LOW = 0;
constexpr uint8_t HIGH = 1;

inline uint32_t fakeMicros = 0;
inline uint32_t fakeMillis = 0;
inline bool fakePinLevels[256] = {};

inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t pin, uint8_t value) { fakePinLevels[pin] = value != 0; }
inline void delayMicroseconds(uint32_t delay) { fakeMicros += delay; }
inline uint32_t micros() { return fakeMicros; }
inline uint32_t millis() { return fakeMillis; }
