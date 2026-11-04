// Analytic sweep of the Doppler loss rules over one pass, for each frequency, bandwidth and SF.
// Prints the elevations at which a packet survives, to compare with Asad Ullah et al., Table 5.
#include "leo_doppler.h"

#include "ns3/core-module.h"
#include "ns3/lorawan-module.h"

#include <iostream>
#include <vector>

using namespace ns3;
using namespace lorawan;

static double
TimeOnAir(int sf, double bandwidthHz, bool ldro, int phyBytes)
{
    LoraTxParameters p;
    p.spreadingFactor = sf;
    p.bandwidthHz = static_cast<uint32_t>(bandwidthHz);
    p.lowDataRateOptimize = ldro;
    return LoraPhy::GetTimeOnAir(phyBytes, p).GetSeconds();
}

static void
Sweep(const char* label, double fcHz, double bandwidthHz, int sf, bool ldro, int phyBytes)
{
    const leo::Orbit orbit(560e3, 0);
    const leo::Vec3 device{leo::kEarthRadiusM, 0, 0};
    const double halfPass = orbit.VisibilityS(1.0) / 2;
    const double toa = TimeOnAir(sf, bandwidthHz, ldro, phyBytes);

    double lo = 1e9;
    double hi = -1e9;
    int ok = 0;
    int total = 0;
    for (double t = -halfPass; t <= halfPass - toa; t += 0.25)
    {
        ++total;
        if (leo::PacketSurvives(orbit, device, fcHz, bandwidthHz, sf, ldro, t, toa))
        {
            const double e = orbit.ElevationDeg(t, device);
            lo = std::min(lo, e);
            hi = std::max(hi, e);
            ++ok;
        }
    }
    std::cout << label << " fc=" << fcHz / 1e6 << " b=" << bandwidthHz / 1e3 << " sf=" << sf
              << " ldro=" << ldro << " toa=" << toa << " survive=" << double(ok) / total
              << " lo=" << (ok ? lo : -1) << " hi=" << (ok ? hi : -1) << std::endl;
}

int
main(int argc, char* argv[])
{
    // Check 1: Table 5 uses LDRO on and a payload that reproduces the paper's stated times on air
    // (149, 821 and 2629 ms for SF7, SF10 and SF12 at 125 kHz).
    for (double fc : {436.7e6, 868e6, 2100e6})
    {
        for (double b : {31.25e3, 62.5e3, 125e3})
        {
            for (int sf : {7, 10, 12})
            {
                Sweep("TABLE", fc, b, sf, true, 60);
            }
        }
    }

    // Check 2: peak Doppler shift and rate over a pass.
    for (double fc : {436.7e6, 868e6})
    {
        const leo::Orbit orbit(560e3, 0);
        const leo::Vec3 device{leo::kEarthRadiusM, 0, 0};
        const double half = orbit.VisibilityS(1.0) / 2;
        double maxShift = 0;
        double maxRate = 0;
        for (double t = -half; t <= half; t += 0.5)
        {
            maxShift = std::max(maxShift, std::abs(orbit.DopplerHz(t, device, fc)));
            maxRate = std::max(maxRate,
                               std::abs(orbit.DopplerHz(t + 0.5, device, fc) -
                                        orbit.DopplerHz(t - 0.5, device, fc)));
        }
        std::cout << "PEAK fc=" << fc / 1e6 << " visibilityS=" << 2 * half
                  << " maxShiftHz=" << maxShift << " maxRateHzPerS=" << maxRate << std::endl;
    }

    // LoRaWAN's real setting at 868 MHz and 125 kHz: LDRO on SF11 and SF12 only.
    for (int sf = 7; sf <= 12; ++sf)
    {
        Sweep("LORAWAN", 868e6, 125e3, sf, sf >= 11, 60);
    }
    return 0;
}
