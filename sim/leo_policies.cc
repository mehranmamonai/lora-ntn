// Spreading-factor policies over repeated LEO passes: moving gateway, path loss, Doppler filter,
// collisions and duty cycle. Devices transmit only above a minimum elevation.
#include "leo_doppler.h"

#include "ns3/core-module.h"
#include "ns3/lorawan-module.h"
#include "ns3/mobility-helper.h"
#include "ns3/point-to-point-helper.h"
#include "ns3/propagation-loss-model.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <string>
#include <unordered_map>
#include <vector>

using namespace ns3;
using namespace lorawan;

namespace
{
constexpr double kFcHz = 868e6;
constexpr double kBandwidthHz = 125e3;
constexpr double kTxPowerDbm = 14;
// TR 38.811 Eq. 6.6-13 with Pfluc of about 1.1 dB for latitude up to 20 deg; 0 dB for 20-60 deg (p. 56).
double g_ionosphericDb = 7.69;

enum Policy
{
    FIXED_SF12,
    STOCK_ADR,
    LINK_ONLY,
    ELEVATION_AWARE,
    ELEVATION_AWARE_LDRO10,
    UNGATED_SF12, // No ephemeris: transmits at SF12 regardless of where the satellite is
    SF12_WINDOW   // SF12, only when its own link and Doppler checks pass
};

const char* const kPolicyNames[] = {"fixed_sf12",
                                    "stock_adr",
                                    "link_only",
                                    "elevation_aware",
                                    "elevation_aware_ldro10",
                                    "ungated_sf12",
                                    "sf12_window"};

double
ElevationDeg(const Vector& sat, const Vector& device)
{
    const leo::Vec3 d{device.x, device.y, device.z};
    const leo::Vec3 los{sat.x - device.x, sat.y - device.y, sat.z - device.z};
    return std::asin(leo::Dot(los, d) / (leo::Norm(los) * leo::Norm(d))) * 180.0 / M_PI;
}

// TR 38.811 rural LOS S-band shadowing, as tabulated in ns-3-ntn. Applied here at 868 MHz.
double
ShadowSigmaDb(double elevationDeg)
{
    static const std::array<double, 9> table{1.79, 1.14, 1.14, 0.92, 1.42, 1.56, 0.85, 0.72, 0.72};
    const int index = std::clamp(int(std::lround(elevationDeg / 10.0)) - 1, 0, 8);
    return table[index];
}

double
FsplDb(double distanceM)
{
    return 20.0 * std::log10(4.0 * M_PI * distanceM * kFcHz / leo::kLightSpeed);
}

class LeoLossModel : public PropagationLossModel
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("LeoLossModel")
                                .SetParent<PropagationLossModel>()
                                .AddConstructor<LeoLossModel>();
        return tid;
    }

    LeoLossModel()
    {
        m_normal = CreateObject<NormalRandomVariable>();
        m_normal->SetAttribute("Mean", DoubleValue(0.0));
        m_normal->SetAttribute("Variance", DoubleValue(1.0));
    }

    void SetTotalGain(double gainDb)
    {
        m_gainDb = gainDb;
    }

    // 1: TR 38.811 rural, per-transmission LOS draw, K per elevation (method of Sant'Ana et al.,
    //    arXiv 2609.07291; values from the ns-3-ntn tables). 2: same, but K fixed at 4 dB from the
    //    rural ray tracing of Chiu et al., arXiv 2611.03869. Variables are created only when
    //    enabled, so mode 0 reproduces the parent exactly.
    void SetChannelMode(int mode)
    {
        m_mode = mode;
        m_losDraw = CreateObject<UniformRandomVariable>();
        for (auto* v : {&m_fadingI, &m_fadingQ, &m_kDraw, &m_nlosShadow})
        {
            *v = CreateObject<NormalRandomVariable>();
            (*v)->SetAttribute("Mean", DoubleValue(0.0));
            (*v)->SetAttribute("Variance", DoubleValue(1.0));
        }
    }

  private:
    double DoCalcRxPower(double txPowerDbm,
                         Ptr<MobilityModel> a,
                         Ptr<MobilityModel> b) const override
    {
        const Vector pa = a->GetPosition();
        const Vector pb = b->GetPosition();
        const bool aIsSat =
            CalculateDistance(pa, Vector(0, 0, 0)) > CalculateDistance(pb, Vector(0, 0, 0));
        const double e = aIsSat ? ElevationDeg(pa, pb) : ElevationDeg(pb, pa);
        // Below the horizon the Earth blocks the link.
        if (e < 0)
        {
            return -300;
        }
        const double shadow = ShadowSigmaDb(e) * m_normal->GetValue();
        const double base = txPowerDbm + m_gainDb - FsplDb(a->GetDistanceFrom(b)) - g_ionosphericDb;
        if (m_mode == 0)
        {
            return base - shadow;
        }
        const int row = std::clamp(int(std::lround(e / 10.0)) - 1, 0, 8);
        static const std::array<double, 9> losProb{0.782, 0.869, 0.919, 0.929, 0.935,
                                                   0.940, 0.949, 0.952, 0.998};
        static const std::array<double, 9> nlosSigma{8.93, 9.08, 8.78, 10.25, 10.56,
                                                     10.74, 10.17, 11.52, 11.52};
        static const std::array<double, 9> nlosCl{19.52, 18.17, 18.42, 18.28, 18.63,
                                                  17.68, 16.5, 16.3, 16.3};
        static const std::array<double, 9> kMean{24.72, 12.31, 8.05, 6.21, 5.04,
                                                 4.42, 3.92, 3.65, 3.59};
        static const std::array<double, 9> kStd{5.07, 5.75, 5.46, 5.23, 3.95,
                                                3.75, 2.56, 1.77, 1.77};
        if (m_losDraw->GetValue(0, 1) >= losProb[row])
        {
            // NLOS: clutter loss, NLOS shadowing and Rayleigh fading.
            const double i = std::sqrt(0.5) * m_fadingI->GetValue();
            const double q = std::sqrt(0.5) * m_fadingQ->GetValue();
            return base - nlosCl[row] - nlosSigma[row] * m_nlosShadow->GetValue() +
                   10.0 * std::log10(i * i + q * q);
        }
        const double kDb = (m_mode == 1) ? kMean[row] + kStd[row] * m_kDraw->GetValue() : 4.0;
        const double k = std::pow(10.0, kDb / 10.0);
        const double scatter = std::sqrt(1.0 / (2 * (k + 1)));
        const double i = std::sqrt(k / (k + 1)) + scatter * m_fadingI->GetValue();
        const double q = scatter * m_fadingQ->GetValue();
        return base - shadow + 10.0 * std::log10(i * i + q * q);
    }

    int64_t DoAssignStreams(int64_t stream) override
    {
        m_normal->SetStream(stream);
        return 1;
    }

    double m_gainDb{5};
    Ptr<NormalRandomVariable> m_normal;
    int m_mode{0};
    Ptr<UniformRandomVariable> m_losDraw;
    Ptr<NormalRandomVariable> m_fadingI;
    Ptr<NormalRandomVariable> m_fadingQ;
    Ptr<NormalRandomVariable> m_kDraw;
    Ptr<NormalRandomVariable> m_nlosShadow;
};

NS_OBJECT_ENSURE_REGISTERED(LeoLossModel);

struct Device
{
    leo::Vec3 pos;
    Ptr<EndDeviceLorawanMac> mac;
    double nextAllowedS = 0;
    int phasePass = -1; // Pass in which the random start was last drawn
};

struct PacketRecord
{
    int device = 0;
    int sf = 0;
    int pass = 0;
    double toa = 0;
};

struct Stats
{
    uint64_t visible = 0;
    uint64_t skipped = 0;
    uint64_t blocked = 0;
    uint64_t usable = 0;
    uint64_t sent = 0;
    uint64_t received = 0;
    uint64_t rejectedDoppler = 0;
    uint64_t underSensitivity = 0;
    uint64_t interfered = 0;
    uint64_t noDemodulator = 0;
    uint64_t sentLast5 = 0;
    uint64_t receivedLast5 = 0;
    double airtimeS = 0;
    uint64_t thinned = 0;
    std::array<uint64_t, 13> sentBySf{};
    std::array<uint64_t, 13> receivedBySf{};
};

Policy g_policy = ELEVATION_AWARE;
double g_gainDb = 5;
double g_marginDb = 3;
double g_minElevationDeg = 10;
double g_periodS = 60;
double g_txProb = 1; // Per-attempt transmit probability
std::vector<uint64_t> g_receivedByDevice;
double g_orbitPeriodS = 0;
double g_predErrorKm = 0; // Along-track error of the device's satellite prediction
bool g_randomPhase = false; // Random start within the duty-cycle interval, once per pass
bool g_windowPhase = false; // Random start among the times the policy would transmit, once per pass
int g_passes = 20;
int g_appBytes = 23; // 32-byte PHY payload; the module adds 9 header bytes and no 4-byte MIC
const leo::Orbit* g_orbit = nullptr;
Ptr<UniformRandomVariable> g_uniform;
std::vector<Device> g_devices;
std::unordered_map<uint32_t, int> g_nodeToDevice;
std::unordered_map<uint64_t, PacketRecord> g_packets;
std::array<double, 13> g_toa{};
Stats g_stats;

bool
Ldro(int sf)
{
    return sf >= ClassAEndDeviceLorawanMac::s_ldroMinSf;
}

// The time at which the true satellite is where the device predicts it to be now. The error has
// the same size for all devices and changes sign between passes. No random draws are used, so a
// zero error reproduces the parent experiment exactly.
double
PredictedTime(double t)
{
    if (g_predErrorKm == 0)
    {
        return t;
    }
    const auto pass = static_cast<uint32_t>(t / g_orbitPeriodS);
    const auto run = static_cast<uint32_t>(RngSeedManager::GetRun());
    const bool ahead = (((pass + 1) * 2654435761U ^ (run * 40503U)) >> 13) & 1U;
    const double offsetS = g_predErrorKm * 1e3 / g_orbit->Speed();
    return ahead ? t + offsetS : t - offsetS;
}

// Mean link budget against the gateway sensitivity, with a margin.
bool
LinkOk(const Vector& sat, const Vector& device, int sf, double marginDb)
{
    const double rx =
        kTxPowerDbm + g_gainDb - FsplDb(CalculateDistance(sat, device)) - g_ionosphericDb;
    return rx - marginDb >= GatewayLoraPhy::SENSITIVITY[sf - 7];
}

bool
DopplerOk(const leo::Vec3& device, int sf, double t)
{
    return leo::PacketSurvives(*g_orbit, device, kFcHz, kBandwidthHz, sf, Ldro(sf), t, g_toa[sf]);
}

// Returns the SF to use, or 0 to skip this attempt.
int
ChooseSf(const Device& d, const Vector& sat, const Vector& pos, double t)
{
    switch (g_policy)
    {
    case FIXED_SF12:
    case UNGATED_SF12:
        return 12;
    case STOCK_ADR:
        return d.mac->GetSfFromDataRate(d.mac->GetDataRate());
    case SF12_WINDOW:
        return (LinkOk(sat, pos, 12, g_marginDb) && DopplerOk(d.pos, 12, t)) ? 12 : 0;
    case LINK_ONLY:
        for (int sf = 7; sf <= 12; ++sf)
        {
            if (LinkOk(sat, pos, sf, g_marginDb))
            {
                return sf;
            }
        }
        return 0;
    case ELEVATION_AWARE:
    case ELEVATION_AWARE_LDRO10:
        for (int sf = 7; sf <= 12; ++sf)
        {
            if (LinkOk(sat, pos, sf, g_marginDb) && DopplerOk(d.pos, sf, t))
            {
                return sf;
            }
        }
        return 0;
    }
    return 0;
}

// Draws only below 1, so p = 1 reproduces earlier experiments exactly.
bool
AdmittedByLoadControl()
{
    if (g_txProb >= 1)
    {
        return true;
    }
    const bool admitted = g_uniform->GetValue(0, 1) < g_txProb;
    g_stats.thinned += !admitted;
    return admitted;
}

// One transmission at a chosen moment inside the predicted window.
void
SendAt(int i)
{
    Device& d = g_devices[i];
    const double t = Simulator::Now().GetSeconds();
    if (t + 1e-9 < d.nextAllowedS)
    {
        return;
    }
    const double tp = PredictedTime(t);
    const auto sp = g_orbit->Position(tp);
    const int sf = ChooseSf(d, Vector(sp.x, sp.y, sp.z), Vector(d.pos.x, d.pos.y, d.pos.z), tp);
    if (sf != 0 && AdmittedByLoadControl())
    {
        d.mac->SetDataRate(12 - sf);
        d.mac->Send(Create<Packet>(g_appBytes));
        d.nextAllowedS = t + 100.0 * g_toa[sf] + 0.01;
    }
}

// Draws this pass's first transmission among the predicted times the policy would transmit,
// limited to the first duty-cycle interval's worth of those times.
void
PlanWindow(int i, double t)
{
    constexpr double stepS = 5.0;
    Device& d = g_devices[i];
    const Vector pos(d.pos.x, d.pos.y, d.pos.z);
    std::vector<double> usable;
    size_t limit = 0;
    for (double tau = t; tau < t + 1200.0; tau += stepS)
    {
        const double tp = PredictedTime(tau);
        const auto sp = g_orbit->Position(tp);
        const Vector sat(sp.x, sp.y, sp.z);
        if (ElevationDeg(sat, pos) < g_minElevationDeg)
        {
            break;
        }
        const int sf = ChooseSf(d, sat, pos, tp);
        if (sf == 0)
        {
            continue;
        }
        if (usable.empty())
        {
            limit = std::max<size_t>(1, size_t(100.0 * g_toa[sf] / stepS));
        }
        usable.push_back(tau);
        if (usable.size() >= limit)
        {
            break;
        }
    }
    if (usable.empty())
    {
        return;
    }
    const auto index = static_cast<size_t>(g_uniform->GetInteger(0, uint32_t(usable.size() - 1)));
    const double start = usable[index] + g_uniform->GetValue(0, stepS);
    d.nextAllowedS = std::max(d.nextAllowedS, start);
    Simulator::Schedule(Seconds(start - t), &SendAt, i);
}

void
Tick(int i)
{
    Device& d = g_devices[i];
    const double t = Simulator::Now().GetSeconds();
    const auto s = g_orbit->Position(t);
    const Vector sat(s.x, s.y, s.z);
    const Vector pos(d.pos.x, d.pos.y, d.pos.z);
    // Policies decide from the predicted satellite; the channel and Doppler filter use the true one.
    const double tPredicted = PredictedTime(t);
    const auto sp = g_orbit->Position(tPredicted);
    const Vector satPredicted(sp.x, sp.y, sp.z);
    if (g_policy == UNGATED_SF12 || ElevationDeg(satPredicted, pos) >= g_minElevationDeg)
    {
        ++g_stats.visible;
        if (g_windowPhase && g_policy != UNGATED_SF12)
        {
            const int windowPass = int(t / g_orbitPeriodS);
            if (d.phasePass != windowPass)
            {
                d.phasePass = windowPass;
                PlanWindow(i, t);
            }
        }
        const int sf = ChooseSf(d, satPredicted, pos, tPredicted);
        if (sf == 0)
        {
            ++g_stats.skipped;
        }
        else
        {
            // Usable contact: this SF would get through without shadowing or collisions.
            if (ElevationDeg(sat, pos) >= 0 && LinkOk(sat, pos, sf, 0) && DopplerOk(d.pos, sf, t))
            {
                ++g_stats.usable;
            }
            // Draws only when enabled, so fixed timing reproduces the parent exactly.
            const int pass = int(t / g_orbitPeriodS);
            if (g_randomPhase && g_policy != UNGATED_SF12 && d.phasePass != pass)
            {
                d.phasePass = pass;
                d.nextAllowedS =
                    std::max(d.nextAllowedS, t + g_uniform->GetValue(0, 100.0 * g_toa[sf]));
            }
            if (t < d.nextAllowedS)
            {
                ++g_stats.blocked;
            }
            else if (AdmittedByLoadControl())
            {
                d.mac->SetDataRate(12 - sf);
                d.mac->Send(Create<Packet>(g_appBytes));
                d.nextAllowedS = t + 100.0 * g_toa[sf] + 0.01;
            }
        }
    }
    Simulator::Schedule(Seconds(g_periodS), &Tick, i);
}

void
OnStartSending(Ptr<const Packet> packet, uint32_t nodeId)
{
    const int i = g_nodeToDevice.at(nodeId);
    const int sf = g_devices[i].mac->GetSfFromDataRate(g_devices[i].mac->GetDataRate());
    const double t = Simulator::Now().GetSeconds();
    PacketRecord r;
    r.device = i;
    r.sf = sf;
    r.pass = int(t / g_orbitPeriodS);
    r.toa = g_toa[sf];
    g_packets[packet->GetUid()] = r;
    ++g_stats.sent;
    ++g_stats.sentBySf[sf];
    g_stats.airtimeS += r.toa;
    g_stats.sentLast5 += r.pass >= g_passes - 5;
}

bool
DopplerFilter(Ptr<const Packet> packet, Time duration)
{
    auto it = g_packets.find(packet->GetUid());
    if (it == g_packets.end())
    {
        return true;
    }
    const PacketRecord& r = it->second;
    const double start = (Simulator::Now() - duration).GetSeconds();
    const bool ok = leo::PacketSurvives(*g_orbit,
                                        g_devices[r.device].pos,
                                        kFcHz,
                                        kBandwidthHz,
                                        r.sf,
                                        Ldro(r.sf),
                                        start,
                                        duration.GetSeconds());
    g_stats.rejectedDoppler += !ok;
    return ok;
}

void
OnReceived(Ptr<const Packet> packet, uint32_t)
{
    auto it = g_packets.find(packet->GetUid());
    if (it != g_packets.end())
    {
        ++g_stats.received;
        ++g_stats.receivedBySf[it->second.sf];
        ++g_receivedByDevice[it->second.device];
        g_stats.receivedLast5 += it->second.pass >= g_passes - 5;
    }
}

void
OnUnderSensitivity(Ptr<const Packet>, uint32_t)
{
    ++g_stats.underSensitivity;
}

void
OnInterfered(Ptr<const Packet>, uint32_t)
{
    ++g_stats.interfered;
}

void
OnNoDemodulator(Ptr<const Packet>, uint32_t)
{
    ++g_stats.noDemodulator;
}
} // namespace

int
main(int argc, char* argv[])
{
    int policy = ELEVATION_AWARE;
    int nDevices = 100;
    double altitudeKm = 560;
    double capRadiusKm = 1000;
    double crossTrackKm = 0;
    int channelMode = 0;
    int rxSet = 0; // 0 ns-3 module, 1 Sant'Ana et al. Table I, 2 SX1301 datasheet Table 12

    CommandLine cmd(__FILE__);
    cmd.AddValue("policy",
                 "0 SF12, 1 ADR, 2 link only, 3 elevation-aware, 4 with LDRO on SF10, 5 ungated SF12, 6 SF12 window",
                 policy);
    cmd.AddValue("nDevices", "Number of end devices", nDevices);
    cmd.AddValue("gainDb", "Gtx + Grx (dBi)", g_gainDb);
    cmd.AddValue("passes", "Number of orbits", g_passes);
    cmd.AddValue("periodS", "Attempt period (s)", g_periodS);
    cmd.AddValue("marginDb", "Link margin used by the policies (dB)", g_marginDb);
    cmd.AddValue("predErrorKm", "Along-track prediction error (km)", g_predErrorKm);
    cmd.AddValue("crossTrackKm", "Largest random cross-track offset per pass (km)", crossTrackKm);
    cmd.AddValue("channelMode", "0 parent, 1 TR 38.811 rural, 2 with K=4 dB", channelMode);
    cmd.AddValue("minElevationDeg", "Minimum elevation (deg)", g_minElevationDeg);
    cmd.AddValue("rxSet", "Gateway sensitivity set", rxSet);
    cmd.AddValue("scintDb", "Ionospheric scintillation loss (dB)", g_ionosphericDb);
    cmd.AddValue("randomPhase", "Random transmit start within each pass", g_randomPhase);
    cmd.AddValue("windowPhase", "Random transmit start inside the predicted window", g_windowPhase);
    cmd.AddValue("dopplerLimits", "Doppler limit mode, see leo_doppler.h", leo::g_dopplerLimits);
    cmd.AddValue("txProb", "Per-attempt transmit probability", g_txProb);
    cmd.Parse(argc, argv);
    g_policy = static_cast<Policy>(policy);
    if (rxSet != 0)
    {
        static const double sets[2][6] = {{-123, -126, -129, -132, -134.5, -137},
                                          {-126.5, -129, -131.5, -134, -136.5, -139.5}};
        std::copy(sets[rxSet - 1], sets[rxSet - 1] + 6, GatewayLoraPhy::SENSITIVITY);
    }

    ClassAEndDeviceLorawanMac::s_ldroMinSf = (g_policy == ELEVATION_AWARE_LDRO10) ? 10 : 11;
    LoraChannel::s_uplinkOnlyToGateways = true;
    Config::SetDefault("ns3::EndDeviceLorawanMac::ADR", BooleanValue(g_policy == STOCK_ADR));

    const leo::Orbit probe(altitudeKm * 1e3, 0);
    g_orbitPeriodS = 2 * M_PI / probe.AngularRate();
    // A negative offset means: use the footprint radius at the minimum elevation for both the
    // largest cross-track offset and the device area.
    if (crossTrackKm < 0)
    {
        crossTrackKm = probe.GroundRangeM(g_minElevationDeg) / 1e3;
        capRadiusKm = crossTrackKm;
    }
    leo::Orbit orbit(altitudeKm * 1e3, g_orbitPeriodS / 2);
    // Drawn only when enabled, so an offset of zero reproduces the parent exactly.
    if (crossTrackKm > 0)
    {
        auto track = CreateObject<UniformRandomVariable>();
        std::vector<double> angles(g_passes);
        for (auto& angle : angles)
        {
            angle = track->GetValue(-crossTrackKm, crossTrackKm) * 1e3 / leo::kEarthRadiusM;
        }
        orbit.SetCrossTrackAngles(angles);
    }
    g_orbit = &orbit;

    for (int sf = 7; sf <= 12; ++sf)
    {
        LoraTxParameters p;
        p.spreadingFactor = sf;
        p.bandwidthHz = static_cast<uint32_t>(kBandwidthHz);
        p.lowDataRateOptimize = Ldro(sf);
        g_toa[sf] = LoraPhy::GetTimeOnAir(g_appBytes + 9, p).GetSeconds();
    }

    auto loss = CreateObject<LeoLossModel>();
    loss->SetTotalGain(g_gainDb);
    if (channelMode != 0)
    {
        loss->SetChannelMode(channelMode);
    }
    Ptr<PropagationDelayModel> delay = CreateObject<ConstantSpeedPropagationDelayModel>();
    auto channel = CreateObject<LoraChannel>(loss, delay);

    LoraPhyHelper phy;
    phy.SetChannel(channel);
    LorawanMacHelper mac;
    mac.SetRegion(LorawanMacHelper::EU);
    LoraHelper helper;

    NodeContainer gateways;
    gateways.Create(1);
    auto gwMobility = CreateObject<LeoOrbitMobility>();
    gwMobility->SetOrbit(orbit);
    gateways.Get(0)->AggregateObject(gwMobility);
    phy.SetDeviceType(LoraPhyHelper::GW);
    mac.SetDeviceType(LorawanMacHelper::GW);
    helper.Install(phy, mac, gateways);

    // Devices uniform over a spherical cap centred under the ground track.
    g_uniform = CreateObject<UniformRandomVariable>();
    g_devices.resize(nDevices);
    auto edPos = CreateObject<ListPositionAllocator>();
    for (auto& d : g_devices)
    {
        const double theta =
            (capRadiusKm * 1e3 / leo::kEarthRadiusM) * std::sqrt(g_uniform->GetValue(0, 1));
        const double alpha = g_uniform->GetValue(0, 2 * M_PI);
        d.pos = {leo::kEarthRadiusM * std::cos(theta),
                 leo::kEarthRadiusM * std::sin(theta) * std::cos(alpha),
                 leo::kEarthRadiusM * std::sin(theta) * std::sin(alpha)};
        edPos->Add(Vector(d.pos.x, d.pos.y, d.pos.z));
    }
    NodeContainer eds;
    eds.Create(nDevices);
    MobilityHelper mobEd;
    mobEd.SetPositionAllocator(edPos);
    mobEd.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobEd.Install(eds);
    auto addrGen = CreateObject<LoraDeviceAddressGenerator>(uint8_t(54), uint32_t(1864));
    phy.SetDeviceType(LoraPhyHelper::ED);
    mac.SetDeviceType(LorawanMacHelper::ED_A);
    mac.SetAddressGenerator(addrGen);
    helper.Install(phy, mac, eds);

    g_receivedByDevice.assign(nDevices, 0);
    for (int i = 0; i < nDevices; ++i)
    {
        auto device = eds.Get(i)->GetDevice(0)->GetObject<LoraNetDevice>();
        g_devices[i].mac = device->GetMac()->GetObject<EndDeviceLorawanMac>();
        g_devices[i].mac->SetDataRate(0);
        g_nodeToDevice[eds.Get(i)->GetId()] = i;
        device->GetPhy()->TraceConnectWithoutContext("StartSending", MakeCallback(&OnStartSending));
        Simulator::Schedule(Seconds(g_uniform->GetValue(0, g_periodS)), &Tick, i);
    }

    auto gwDevice = gateways.Get(0)->GetDevice(0)->GetObject<LoraNetDevice>();
    auto gwPhy = DynamicCast<SimpleGatewayLoraPhy>(gwDevice->GetPhy());
    gwPhy->SetReceiveFilter(MakeCallback(&DopplerFilter));
    gwPhy->TraceConnectWithoutContext("ReceivedPacket", MakeCallback(&OnReceived));
    gwPhy->TraceConnectWithoutContext("LostPacketBecauseUnderSensitivity",
                                      MakeCallback(&OnUnderSensitivity));
    gwPhy->TraceConnectWithoutContext("LostPacketBecauseInterference", MakeCallback(&OnInterfered));
    gwPhy->TraceConnectWithoutContext("LostPacketBecauseNoMoreReceivers",
                                      MakeCallback(&OnNoDemodulator));

    Ptr<Node> server = CreateObject<Node>();
    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue("5Mbps"));
    p2p.SetChannelAttribute("Delay", StringValue("2ms"));
    P2PGwRegistration_t reg;
    auto c = p2p.Install(server, gateways.Get(0));
    reg.emplace_back(DynamicCast<PointToPointNetDevice>(c.Get(0)), gateways.Get(0));
    NetworkServerHelper ns;
    ns.EnableAdr(g_policy == STOCK_ADR);
    if (g_policy == STOCK_ADR)
    {
        ns.SetAdr("ns3::AdrComponent");
    }
    ns.SetGatewaysP2P(reg);
    ns.SetEndDevices(eds);
    ns.Install(server);
    ForwarderHelper fwd;
    fwd.Install(gateways);

    Simulator::Stop(Seconds(g_orbitPeriodS * g_passes));
    Simulator::Run();

    int changed = 0;
    for (const auto& d : g_devices)
    {
        changed += d.mac->GetDataRate() != 0;
    }
    Simulator::Destroy();

    const Stats& s = g_stats;
    double sumReceived = 0;
    double sumSquared = 0;
    int served = 0;
    for (const uint64_t r : g_receivedByDevice)
    {
        sumReceived += double(r);
        sumSquared += double(r) * double(r);
        served += r > 0;
    }
    const double jain = sumSquared > 0 ? sumReceived * sumReceived / (nDevices * sumSquared) : 0;
    std::cout << "RUN policy=" << kPolicyNames[policy] << " gain=" << g_gainDb << " n=" << nDevices
              << " seed=" << RngSeedManager::GetRun() << " errorKm=" << g_predErrorKm
              << " randomPhase=" << g_randomPhase << " windowPhase=" << g_windowPhase
              << " crossTrackKm=" << crossTrackKm << " marginDb=" << g_marginDb
              << " channelMode=" << channelMode << " minElevationDeg=" << g_minElevationDeg
              << " rxSet=" << rxSet << " scintDb=" << g_ionosphericDb
              << " dopplerLimits=" << leo::g_dopplerLimits << " txProb=" << g_txProb
              << " thinned=" << s.thinned << " jain=" << jain << " served=" << served
              << " capRadiusKm=" << capRadiusKm
              << " passes=" << g_passes
              << " orbitS=" << g_orbitPeriodS << " visible=" << s.visible
              << " skipped=" << s.skipped << " blocked=" << s.blocked << " usable=" << s.usable
              << " sent=" << s.sent << " received=" << s.received
              << " rejDoppler=" << s.rejectedDoppler << " underSens=" << s.underSensitivity
              << " interfered=" << s.interfered << " noDemod=" << s.noDemodulator
              << " sentLast5=" << s.sentLast5 << " recvLast5=" << s.receivedLast5
              << " airtimeS=" << s.airtimeS << " finalDrNonzero=" << changed;
    for (int sf = 7; sf <= 12; ++sf)
    {
        std::cout << " sentSf" << sf << "=" << s.sentBySf[sf] << " recvSf" << sf << "="
                  << s.receivedBySf[sf];
    }
    std::cout << std::endl;
    return 0;
}
