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
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <set>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

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
    SF12_WINDOW,  // SF12, only when its own link and Doppler checks pass
    CONTROLLED    // Link-only with per-device margin, SF12 elevation cut-off and p from beacons
};

const char* const kPolicyNames[] = {"fixed_sf12",
                                    "stock_adr",
                                    "link_only",
                                    "elevation_aware",
                                    "elevation_aware_ldro10",
                                    "ungated_sf12",
                                    "sf12_window",
                                    "controlled"};

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
    // Settings of the controlled policy, as last received in a beacon.
    double marginDb = 0;
    double txProb = 1;
    double thetaDeg = 90;
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
// Controlled policy: exploration probability for SF12 above the cut-off, and the settings the
// satellite currently broadcasts in its beacons.
double g_exploreProb = 0;
double g_beaconTxProb = 1;
double g_beaconMarginDb = 0;
double g_beaconThetaDeg = 90;
bool g_instantSettings = false; // Controlled policy: apply settings to all devices at once, no beacon
// Controlled policy: SF12 cut-off every device holds from the start (review baseline: best fixed
// threshold). 90 keeps every earlier experiment unchanged.
double g_initThetaDeg = 90;
// A/B test of two cut-offs within a pass: devices with an odd index (odd device address, known to the
// network) take this cut-off from beacons, devices with an even index take g_beaconThetaDeg. Negative
// means the same cut-off for all, which keeps every earlier experiment unchanged.
double g_beaconThetaOddDeg = -1;
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

// Per-pass counters. Observed: what a satellite gateway sees in received packets. Truth: for
// analysis only, never sent to the controller.
struct PassRecord
{
    uint64_t received = 0;
    uint64_t receivedOdd = 0; // From devices with an odd address (gateway-observable)
    std::array<uint64_t, 13> receivedBySf{};
    std::set<int> devicesHeard;
    double rssiSumDbm = 0;
    double rssiMinDbm = 0;
    uint64_t rssiCount = 0;
    // Received SF11 and SF12 packets in 10-degree elevation bins from 20 to 90 deg, and packets
    // received within 1 dB of the gateway's own sensitivity. Both are gateway-observable.
    std::array<uint64_t, 7> sf11ByElevation{};
    std::array<uint64_t, 7> sf12ByElevation{};
    uint64_t nearSensitivity = 0;
    double thetaDeg = 90;
    double thetaOddDeg = -1;
    uint64_t beaconsHeard = 0;
    uint64_t beaconsMissed = 0;
    uint64_t sent = 0;
    uint64_t rejectedDoppler = 0;
    uint64_t underSensitivity = 0;
    uint64_t interfered = 0;
    uint64_t noDemodulator = 0;
    double txProb = 1;
    double marginDb = 0;
};

std::vector<PassRecord> g_pass;
std::set<int> g_everHeard; // Distinct devices heard since the start (device addresses)

int
PassAt(double t)
{
    return std::clamp(int(t / g_orbitPeriodS), 0, int(g_pass.size()) - 1);
}

// External controller, started only when --controller is given. One JSON line each way per pass.
struct Controller
{
    pid_t pid = -1;
    FILE* toChild = nullptr;
    FILE* fromChild = nullptr;
};

Controller g_controller;

void
StartController(const std::string& command)
{
    int down[2];
    int up[2];
    if (pipe(down) != 0 || pipe(up) != 0)
    {
        NS_FATAL_ERROR("Could not create controller pipes");
    }
    const pid_t pid = fork();
    if (pid < 0)
    {
        NS_FATAL_ERROR("Could not start the controller");
    }
    if (pid == 0)
    {
        dup2(down[0], STDIN_FILENO);
        dup2(up[1], STDOUT_FILENO);
        close(down[1]);
        close(up[0]);
        execl("/bin/sh", "sh", "-c", command.c_str(), static_cast<char*>(nullptr));
        _exit(127);
    }
    close(down[0]);
    close(up[1]);
    g_controller.pid = pid;
    g_controller.toChild = fdopen(down[1], "w");
    g_controller.fromChild = fdopen(up[0], "r");
}

void
StopController()
{
    if (g_controller.pid < 0)
    {
        return;
    }
    fclose(g_controller.toChild);
    fclose(g_controller.fromChild);
    int status = 0;
    waitpid(g_controller.pid, &status, 0);
    g_controller.pid = -1;
}

// Reads a number following "key": in a one-line JSON reply.
double
JsonNumber(const std::string& line, const std::string& key)
{
    const auto at = line.find("\"" + key + "\"");
    if (at == std::string::npos)
    {
        NS_FATAL_ERROR("Controller reply lacks " << key << ": " << line);
    }
    const auto colon = line.find(':', at);
    return std::strtod(line.c_str() + colon + 1, nullptr);
}

// The only message the controller receives. Holds gateway-observable fields only.
std::string
ObservationJson(int pass)
{
    const PassRecord& r = g_pass[pass];
    std::ostringstream o;
    o.precision(10);
    o << "{\"pass\":" << pass << ",\"received\":" << r.received << ",\"received_by_sf\":{";
    for (int sf = 7; sf <= 12; ++sf)
    {
        o << "\"" << sf << "\":" << r.receivedBySf[sf] << (sf < 12 ? "," : "");
    }
    o << "},\"devices_heard\":" << r.devicesHeard.size() << ",\"rssi_mean_dbm\":";
    if (r.rssiCount > 0)
    {
        o << r.rssiSumDbm / double(r.rssiCount) << ",\"rssi_min_dbm\":" << r.rssiMinDbm;
    }
    else
    {
        o << "null,\"rssi_min_dbm\":null";
    }
    o << ",\"received_odd\":" << r.receivedOdd;
    o << ",\"near_sensitivity\":" << r.nearSensitivity << ",\"devices_heard_total\":" << g_everHeard.size();
    for (const auto& [key, bins] : {std::make_pair("sf11_by_elevation", &r.sf11ByElevation),
                                    std::make_pair("sf12_by_elevation", &r.sf12ByElevation)})
    {
        o << ",\"" << key << "\":[";
        for (size_t b = 0; b < bins->size(); ++b)
        {
            o << (*bins)[b] << (b + 1 < bins->size() ? "," : "");
        }
        o << "]";
    }
    o << "}";
    return o.str();
}

// At each pass boundary: report the finished pass, apply the reply to the next pass.
void
ControlStep(int finishedPass)
{
    const std::string observation = ObservationJson(finishedPass);
    std::cout << "OBS " << observation << std::endl;
    fprintf(g_controller.toChild, "%s\n", observation.c_str());
    fflush(g_controller.toChild);
    char buffer[4096];
    if (!fgets(buffer, sizeof(buffer), g_controller.fromChild))
    {
        NS_FATAL_ERROR("Controller closed its output at pass " << finishedPass);
    }
    const std::string reply(buffer);
    const double p = JsonNumber(reply, "p");
    const double margin = JsonNumber(reply, "margin_db");
    const double theta = reply.find("\"theta_deg\"") == std::string::npos ? 90 : JsonNumber(reply, "theta_deg");
    const double thetaOdd =
        reply.find("\"theta_odd_deg\"") == std::string::npos ? -1 : JsonNumber(reply, "theta_odd_deg");
    if (p < 0 || p > 1)
    {
        NS_FATAL_ERROR("Controller returned p outside [0, 1]: " << reply);
    }
    if (g_policy == CONTROLLED)
    {
        // Reaches devices only through beacons.
        g_beaconTxProb = p;
        g_beaconMarginDb = margin;
        g_beaconThetaDeg = theta;
        g_beaconThetaOddDeg = thetaOdd;
        if (g_instantSettings)
        {
            // Test of beacon reach: every device gets the new settings at the pass boundary.
            for (size_t i = 0; i < g_devices.size(); ++i)
            {
                auto& d = g_devices[i];
                d.txProb = p;
                d.marginDb = margin;
                d.thetaDeg = (i % 2 == 1 && thetaOdd >= 0) ? thetaOdd : theta;
            }
        }
    }
    else
    {
        g_txProb = p;
        g_marginDb = margin;
    }
    g_pass[finishedPass + 1].txProb = p;
    g_pass[finishedPass + 1].marginDb = margin;
    g_pass[finishedPass + 1].thetaDeg = theta;
    g_pass[finishedPass + 1].thetaOddDeg = thetaOdd;
}

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
    case CONTROLLED:
        for (int sf = 7; sf <= 12; ++sf)
        {
            if (LinkOk(sat, pos, sf, d.marginDb))
            {
                // Above the learned cut-off SF12 is skipped, except for exploration. Draws only
                // when exploring, so frozen settings reproduce link-only exactly.
                if (sf == 12 && ElevationDeg(sat, pos) > d.thetaDeg &&
                    !(g_exploreProb > 0 && g_uniform->GetValue(0, 1) < g_exploreProb))
                {
                    return 0;
                }
                return sf;
            }
        }
        return 0;
    }
    return 0;
}

// Draws only below 1, so p = 1 reproduces earlier experiments exactly.
bool
AdmittedByLoadControl(const Device& d)
{
    const double p = g_policy == CONTROLLED ? d.txProb : g_txProb;
    if (p >= 1)
    {
        return true;
    }
    const bool admitted = g_uniform->GetValue(0, 1) < p;
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
    if (sf != 0 && AdmittedByLoadControl(d))
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
            else if (AdmittedByLoadControl(d))
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
    ++g_pass[PassAt(t)].sent;
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
    g_pass[PassAt(Simulator::Now().GetSeconds())].rejectedDoppler += !ok;
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
        PassRecord& p = g_pass[PassAt(Simulator::Now().GetSeconds())];
        ++p.received;
        p.receivedOdd += it->second.device % 2;
        ++p.receivedBySf[it->second.sf];
        p.devicesHeard.insert(it->second.device);
        g_everHeard.insert(it->second.device);
        // The gateway knows each packet's arrival time and its own orbit, hence the elevation.
        const int sf = it->second.sf;
        if (sf == 11 || sf == 12)
        {
            const auto s = g_orbit->Position(Simulator::Now().GetSeconds());
            const auto& dp = g_devices[it->second.device].pos;
            const double e = ElevationDeg(Vector(s.x, s.y, s.z), Vector(dp.x, dp.y, dp.z));
            const int bin = std::clamp(int((e - 20) / 10), 0, 6);
            if (e >= 20)
            {
                ++(sf == 11 ? p.sf11ByElevation : p.sf12ByElevation)[bin];
            }
        }
    }
}

// The gateway PHY attaches the receive power only after its ReceivedPacket trace fires, just before
// handing the packet to the MAC, so the power is read from the MAC trace instead.
void
OnGatewayMacReceived(Ptr<const Packet> packet)
{
    LoraTag tag;
    if (!packet->PeekPacketTag(tag))
    {
        return;
    }
    PassRecord& p = g_pass[PassAt(Simulator::Now().GetSeconds())];
    const double rssi = tag.GetReceivePower();
    p.rssiMinDbm = p.rssiCount == 0 ? rssi : std::min(p.rssiMinDbm, rssi);
    p.rssiSumDbm += rssi;
    ++p.rssiCount;
    const int sf = tag.GetSpreadingFactor();
    if (sf >= 7 && sf <= 12 && rssi < GatewayLoraPhy::SENSITIVITY[sf - 7] + 1)
    {
        ++p.nearSensitivity;
    }
}

// Beacon every 128 s (LoRaWAN L2 v1.0.4, PDF p. 59) at SF9. A device adopts the broadcast settings
// only if the downlink reaches the SX1276 SF9 sensitivity of -129 dBm (datasheet PDF p. 20);
// otherwise it keeps its last settings (beaconless operation, L2 PDF p. 57). Satellite power is
// 500 mW e.r.p. (ERC 70-03 band h1.7), 29.15 dBm e.i.r.p., with no device antenna gain.
constexpr double kBeaconPeriodS = 128;
constexpr double kBeaconEirpDbm = 29.15;
constexpr double kDeviceSf9SensitivityDbm = -129;
Ptr<NormalRandomVariable> g_beaconShadow;

void
Beacon()
{
    const double t = Simulator::Now().GetSeconds();
    const auto s = g_orbit->Position(t);
    const Vector sat(s.x, s.y, s.z);
    PassRecord& p = g_pass[PassAt(t)];
    for (size_t i = 0; i < g_devices.size(); ++i)
    {
        auto& d = g_devices[i];
        const Vector pos(d.pos.x, d.pos.y, d.pos.z);
        const double e = ElevationDeg(sat, pos);
        if (e < g_minElevationDeg)
        {
            continue;
        }
        const double rx = kBeaconEirpDbm - FsplDb(CalculateDistance(sat, pos)) - g_ionosphericDb -
                          ShadowSigmaDb(e) * g_beaconShadow->GetValue();
        if (rx >= kDeviceSf9SensitivityDbm)
        {
            d.txProb = g_beaconTxProb;
            d.marginDb = g_beaconMarginDb;
            d.thetaDeg = (i % 2 == 1 && g_beaconThetaOddDeg >= 0) ? g_beaconThetaOddDeg : g_beaconThetaDeg;
            ++p.beaconsHeard;
        }
        else
        {
            ++p.beaconsMissed;
        }
    }
    Simulator::Schedule(Seconds(kBeaconPeriodS), &Beacon);
}

void
OnUnderSensitivity(Ptr<const Packet>, uint32_t)
{
    ++g_stats.underSensitivity;
    ++g_pass[PassAt(Simulator::Now().GetSeconds())].underSensitivity;
}

void
OnInterfered(Ptr<const Packet>, uint32_t)
{
    ++g_stats.interfered;
    ++g_pass[PassAt(Simulator::Now().GetSeconds())].interfered;
}

void
OnNoDemodulator(Ptr<const Packet>, uint32_t)
{
    ++g_stats.noDemodulator;
    ++g_pass[PassAt(Simulator::Now().GetSeconds())].noDemodulator;
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
    cmd.AddValue("exploreProb", "Controlled policy: probability of SF12 above the cut-off", g_exploreProb);
    bool beacons = true;
    cmd.AddValue("beacons", "Controlled policy: deliver settings by beacon (1) or not at all (0)", beacons);
    cmd.AddValue("thetaDeg", "Controlled policy: SF12 elevation cut-off held by every device from the start",
                 g_initThetaDeg);
    cmd.AddValue("instantSettings", "Controlled policy: apply settings to every device at the pass boundary",
                 g_instantSettings);
    int collision = 1;
    cmd.AddValue("collision",
                 "1 Goursaud (ns-3 default), 2 Croce et al. 2018 Table II, 3 Croce plus receiver "
                 "locking (Bor et al. 2016)",
                 collision);
    std::string controller;
    cmd.AddValue("controller",
                 "External per-pass controller command, words separated by commas (ns-3 cuts option "
                 "values at spaces); empty for none",
                 controller);
    cmd.Parse(argc, argv);
    std::replace(controller.begin(), controller.end(), ',', ' ');
    if (collision == 3)
    {
        // C3: the C2 thresholds plus the receiver-locking rule of Bor et al. 2016 (PDF p. 5,
        // Fig. 3 and Eq. 10), added to LoraInterferenceHelper by scripts/patch_lorawan.py.
        LoraInterferenceHelper::s_lockRule = true;
    }
    if (collision == 2 || collision == 3)
    {
        // Croce et al., IEEE Comms Letters 2018, Table II (PDF p. 4): SIR thresholds measured on an
        // SX1272. Rows wanted SF7-12, columns interferer SF7-12, same orientation as ns-3 uses.
        LoraInterferenceHelper::collisionSnirGoursaud = {{1, -8, -9, -9, -9, -9},
                                                         {-11, 1, -11, -12, -13, -13},
                                                         {-15, -13, 1, -13, -14, -15},
                                                         {-19, -18, -17, 1, -17, -18},
                                                         {-22, -22, -21, -20, 1, -20},
                                                         {-25, -25, -25, -24, -23, 1}};
    }
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
    gwDevice->GetMac()->TraceConnectWithoutContext("ReceivedPacket",
                                                   MakeCallback(&OnGatewayMacReceived));

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

    g_pass.assign(g_passes, PassRecord{});
    g_pass[0].txProb = g_txProb;
    g_pass[0].marginDb = g_marginDb;
    if (!controller.empty())
    {
        StartController(controller);
        for (int k = 1; k < g_passes; ++k)
        {
            Simulator::Schedule(Seconds(k * g_orbitPeriodS), &ControlStep, k - 1);
        }
    }
    // Controlled policy: every device starts from the run's settings; beacons then deliver changes.
    if (g_policy == CONTROLLED)
    {
        g_beaconTxProb = g_txProb;
        g_beaconMarginDb = g_marginDb;
        for (auto& d : g_devices)
        {
            d.txProb = g_txProb;
            d.marginDb = g_marginDb;
            d.thetaDeg = g_initThetaDeg;
        }
        g_beaconThetaDeg = g_initThetaDeg;
        g_pass[0].thetaDeg = g_initThetaDeg;
        if (beacons)
        {
            // Created after every other random variable, so its stream leaves theirs unchanged.
            g_beaconShadow = CreateObject<NormalRandomVariable>();
            Simulator::Schedule(Seconds(0), &Beacon);
        }
    }

    Simulator::Stop(Seconds(g_orbitPeriodS * g_passes));
    Simulator::Run();
    if (!controller.empty())
    {
        // The last pass is reported too, so the controller sees every pass; its reply is unused.
        std::cout << "OBS " << ObservationJson(g_passes - 1) << std::endl;
        StopController();
        for (int k = 0; k < g_passes; ++k)
        {
            const PassRecord& r = g_pass[k];
            std::cout << "PASS pass=" << k << " p=" << r.txProb << " marginDb=" << r.marginDb
                      << " thetaDeg=" << r.thetaDeg << " thetaOddDeg=" << r.thetaOddDeg
                      << " receivedOdd=" << r.receivedOdd << " sent=" << r.sent
                      << " received=" << r.received << " rejDoppler=" << r.rejectedDoppler
                      << " underSens=" << r.underSensitivity << " interfered=" << r.interfered
                      << " noDemod=" << r.noDemodulator << " beaconsHeard=" << r.beaconsHeard
                      << " beaconsMissed=" << r.beaconsMissed << std::endl;
        }
    }

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
              << " collision=" << collision << " lockLost=" << LoraInterferenceHelper::s_lockLost
              << " exploreProb=" << g_exploreProb << " beacons=" << beacons
              << " thetaFixedDeg=" << g_initThetaDeg;
    uint64_t heard = 0;
    uint64_t missed = 0;
    for (const auto& r : g_pass)
    {
        heard += r.beaconsHeard;
        missed += r.beaconsMissed;
    }
    std::cout << " beaconsHeard=" << heard << " beaconsMissed=" << missed
              << " controller=" << (controller.empty() ? 0 : 1)
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
