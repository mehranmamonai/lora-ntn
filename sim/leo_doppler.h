// Circular-orbit LEO geometry and the LoRa Doppler loss rules of Asad Ullah et al.,
// "Understanding the Limits of LoRa Direct-to-Satellite: The Doppler Perspectives" (OJCOMS 2024).
// Coordinates are Earth-centred, in metres. Earth rotation is ignored, as in the paper's Eqs. (7)-(9).
#ifndef LEO_DOPPLER_H
#define LEO_DOPPLER_H

#include "ns3/mobility-model.h"
#include "ns3/simulator.h"

#include <cmath>

namespace leo
{

constexpr double kEarthRadiusM = 6371e3;
constexpr double kGravity = 9.80665;
constexpr double kLightSpeed = 299792458.0;

struct Vec3
{
    double x = 0;
    double y = 0;
    double z = 0;
};

inline double
Dot(const Vec3& a, const Vec3& b)
{
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

inline Vec3
Sub(const Vec3& a, const Vec3& b)
{
    return {a.x - b.x, a.y - b.y, a.z - b.z};
}

inline double
Norm(const Vec3& a)
{
    return std::sqrt(Dot(a, a));
}

// Circular orbit in the x-y plane, overhead (R, 0, 0) at time tCentreS.
class Orbit
{
  public:
    Orbit(double altitudeM, double tCentreS)
        : m_h(altitudeM),
          m_t0(tCentreS)
    {
    }

    double Speed() const // v = sqrt(g R / (1 + H/R))
    {
        return std::sqrt(kGravity * kEarthRadiusM / (1 + m_h / kEarthRadiusM));
    }

    double AngularRate() const // Eq. (9)
    {
        return std::sqrt(kGravity / kEarthRadiusM) * std::pow(1 + m_h / kEarthRadiusM, -1.5);
    }

    Vec3 Position(double tS) const
    {
        const double phi = AngularRate() * (tS - m_t0);
        const double r = kEarthRadiusM + m_h;
        return {r * std::cos(phi), r * std::sin(phi), 0};
    }

    Vec3 Velocity(double tS) const
    {
        const double phi = AngularRate() * (tS - m_t0);
        const double v = Speed();
        return {-v * std::sin(phi), v * std::cos(phi), 0};
    }

    double ElevationDeg(double tS, const Vec3& device) const
    {
        const Vec3 los = Sub(Position(tS), device);
        return std::asin(Dot(los, device) / (Norm(los) * Norm(device))) * 180.0 / M_PI;
    }

    // Eqs. (5), (7), (8): received minus transmitted carrier, in Hz.
    double DopplerHz(double tS, const Vec3& device, double fcHz) const
    {
        const Vec3 toDevice = Sub(device, Position(tS));
        const double v = Speed();
        const double cosBeta = -Dot(Velocity(tS), toDevice) / (v * Norm(toDevice));
        return fcHz / (1 + v / kLightSpeed * cosBeta) - fcHz;
    }

    // Total visibility time above a minimum elevation, Eqs. (1), (3), (4).
    double VisibilityS(double minElevationDeg) const
    {
        const double e = minElevationDeg * M_PI / 180.0;
        const double ratio = (m_h + kEarthRadiusM) / kEarthRadiusM;
        const double d = kEarthRadiusM *
                         (std::sqrt(ratio * ratio - std::cos(e) * std::cos(e)) - std::sin(e));
        const double dg = kEarthRadiusM * std::asin(d * std::cos(e) / (m_h + kEarthRadiusM));
        return 2 * dg / Speed();
    }

  private:
    double m_h;
    double m_t0;
};

// Eq. (10)
inline double
StaticLimitHz(double bandwidthHz)
{
    return 0.25 * bandwidthHz;
}

// Eq. (11)
inline double
DynamicLimitHz(double bandwidthHz, int sf, bool ldro)
{
    return (ldro ? 16.0 : 1.0) * bandwidthHz / (3.0 * std::pow(2.0, sf));
}

// Eqs. (12)-(14): true if the packet survives Doppler.
inline bool
PacketSurvives(const Orbit& orbit,
               const Vec3& device,
               double fcHz,
               double bandwidthHz,
               int sf,
               bool ldro,
               double tStartS,
               double toaS)
{
    const double fStart = orbit.DopplerHz(tStartS, device, fcHz);
    const double fEnd = orbit.DopplerHz(tStartS + toaS, device, fcHz);
    return std::abs(fStart) < StaticLimitHz(bandwidthHz) &&
           std::abs(fStart - fEnd) < DynamicLimitHz(bandwidthHz, sf, ldro);
}

} // namespace leo

namespace ns3
{

// ns-3 mobility model following leo::Orbit.
class LeoOrbitMobility : public MobilityModel
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("LeoOrbitMobility")
                                .SetParent<MobilityModel>()
                                .AddConstructor<LeoOrbitMobility>();
        return tid;
    }

    LeoOrbitMobility()
        : m_orbit(600e3, 0)
    {
    }

    void SetOrbit(const leo::Orbit& orbit)
    {
        m_orbit = orbit;
    }

    Ptr<MobilityModel> Copy() const override
    {
        return CreateObject<LeoOrbitMobility>(*this);
    }

  private:
    Vector DoGetPosition() const override
    {
        const auto p = m_orbit.Position(Simulator::Now().GetSeconds());
        return Vector(p.x, p.y, p.z);
    }

    void DoSetPosition(const Vector&) override
    {
    }

    Vector DoGetVelocity() const override
    {
        const auto v = m_orbit.Velocity(Simulator::Now().GetSeconds());
        return Vector(v.x, v.y, v.z);
    }

    leo::Orbit m_orbit;
};

NS_OBJECT_ENSURE_REGISTERED(LeoOrbitMobility);

} // namespace ns3

#endif // LEO_DOPPLER_H
