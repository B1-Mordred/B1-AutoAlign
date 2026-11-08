#include <assert.h>
#include <stdint.h>

#include "EndstopInput.h"

static void testDebounceAndRelease()
{
    constexpr uint8_t pin = 39;
    fakePinLevels[pin] = false;
    DebouncedEndstop endstop(pin, 5);
    endstop.begin(100);
    assert(!endstop.isActive());

    fakePinLevels[pin] = true;
    assert(!endstop.service(101));
    assert(!endstop.service(105));
    assert(endstop.service(106));
    assert(endstop.isActive());

    // A short bounce must not clear a stable active limit.
    fakePinLevels[pin] = false;
    assert(!endstop.service(107));
    fakePinLevels[pin] = true;
    assert(!endstop.service(108));
    assert(endstop.isActive());

    fakePinLevels[pin] = false;
    assert(!endstop.service(109));
    assert(endstop.service(114));
    assert(!endstop.isActive());
}

static void testTimerWrap()
{
    constexpr uint8_t pin = 36;
    fakePinLevels[pin] = false;
    DebouncedEndstop endstop(pin, 5);
    endstop.begin(UINT32_MAX - 3U);
    fakePinLevels[pin] = true;
    assert(!endstop.service(UINT32_MAX - 2U));
    assert(endstop.service(3));
    assert(endstop.isActive());
}

static void testDirectionPolicy()
{
    assert(endstopBlocksDirection(true, true, EndstopSide::Minimum, -1));
    assert(!endstopBlocksDirection(true, true, EndstopSide::Minimum, 1));
    assert(endstopBlocksDirection(true, true, EndstopSide::Maximum, 1));
    assert(!endstopBlocksDirection(true, true, EndstopSide::Maximum, -1));
    assert(!endstopBlocksDirection(false, true, EndstopSide::Minimum, -1));
    assert(!endstopBlocksDirection(true, false, EndstopSide::Minimum, -1));
}

int main()
{
    testDebounceAndRelease();
    testTimerWrap();
    testDirectionPolicy();
    return 0;
}
