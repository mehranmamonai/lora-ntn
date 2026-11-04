// Static LoRa gateway at satellite altitude, following Traspadini et al. (GLOBECOM 2025):
// one gateway above a circular beam footprint, FSPL + ionospheric loss + log-normal shadowing,
// spreading factors assigned once from received power.
#include "ns3/core-module.h"
#include "ns3/lorawan-module.h"
#include "ns3/mobility-helper.h"
#include "ns3/point-to-point-helper.h"
#include "ns3/propagation-loss-model.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <utility>

using namespace ns3;
using namespace lorawan;

// Path loss of Eq. (6)-(8) in the paper. Shadowing is drawn once per link and then held,
// because the geometry is static.
class NtnLossModel : public PropagationLossModel
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("NtnLossModel")
                                .SetParent<PropagationLossModel>()
                                .AddConstructor<NtnLossModel>();
        return tid;
    }

    NtnLossModel()
    {
        m_normal = CreateObject<NormalRandomVariable>();
    }

    void Configure(double freqHz, double atmosphericDb, double totalGainDb, double sigmaDb)
    {
        m_freqHz = freqHz;
        m_atmosphericDb = atmosphericDb;
        m_totalGainDb = totalGainDb;
        m_normal->SetAttribute("Mean", DoubleValue(0.0));
        m_normal->SetAttribute("Variance", DoubleValue(sigmaDb * sigmaDb));
    }

  private:
    double DoCalcRxPower(double txPowerDbm,
                         Ptr<MobilityModel> a,
                         Ptr<MobilityModel> b) const override
    {
        const double lambda = 299792458.0 / m_freqHz;
        const double d = a->GetDistanceFrom(b);
        const double fspl = 20.0 * std::log10(4.0 * M_PI * d / lambda);
        const MobilityModel* pa = PeekPointer(a);
        const MobilityModel* pb = PeekPointer(b);
        const std::pair<const MobilityModel*, const MobilityModel*> key(std::min(pa, pb),
                                                                        std::max(pa, pb));
        auto it = m_shadow.find(key);
        if (it == m_shadow.end())
        {
            it = m_shadow.emplace(key, m_normal->GetValue()).first;
        }
        return txPowerDbm + m_totalGainDb - fspl - m_atmosphericDb - it->second;
    }

    int64_t DoAssignStreams(int64_t stream) override
    {
        m_normal->SetStream(stream);
        return 1;
    }

    double m_freqHz{868e6};
    double m_atmosphericDb{0};
    double m_totalGainDb{0};
    Ptr<NormalRandomVariable> m_normal;
    mutable std::map<std::pair<const MobilityModel*, const MobilityModel*>, double> m_shadow;
};

NS_OBJECT_ENSURE_REGISTERED(NtnLossModel);

int
main(int argc, char* argv[])
{
    double altitudeKm = 600;
    double beamwidthDeg = 5;
    double totalGainDb = 5;
    double densityPerKm2 = 0.01;
    double atmosphericDb = 7.7; // (0.868/4)^-1.5 * 1.1 / sqrt(2), Eq. (7) with Pf(4 GHz) = 1.1 dB
    double sigmaDb = 0.72;      // TR 38.811 rural LOS shadowing near zenith
    double periodS = 60;
    int nPeriods = 20;
    int appBytes = 19; // 32-byte PHY payload minus the 13-byte LoRaWAN header
    std::string csv = "devices.csv";

    CommandLine cmd(__FILE__);
    cmd.AddValue("altitudeKm", "Gateway altitude (km)", altitudeKm);
    cmd.AddValue("beamwidthDeg", "Antenna beamwidth (deg)", beamwidthDeg);
    cmd.AddValue("totalGainDb", "Gtx + Grx (dBi)", totalGainDb);
    cmd.AddValue("atmosphericDb", "Ionospheric loss (dB)", atmosphericDb);
    cmd.AddValue("sigmaDb", "Shadowing standard deviation (dB)", sigmaDb);
    cmd.AddValue("periodS", "Uplink period (s)", periodS);
    cmd.AddValue("nPeriods", "Number of periods", nPeriods);
    cmd.AddValue("csv", "Per-device output CSV", csv);
    cmd.Parse(argc, argv);

    const double h = altitudeKm * 1e3;
    const double radiusM = std::tan(beamwidthDeg / 2.0 * M_PI / 180.0) * h;
    const int nDevices =
        std::max<int>(1, std::lround(densityPerKm2 * M_PI * (radiusM / 1e3) * (radiusM / 1e3)));

    Config::SetDefault("ns3::EndDeviceLorawanMac::ADR", BooleanValue(false));

    auto loss = CreateObject<NtnLossModel>();
    loss->Configure(868e6, atmosphericDb, totalGainDb, sigmaDb);
    Ptr<PropagationDelayModel> delay = CreateObject<ConstantSpeedPropagationDelayModel>();
    auto channel = CreateObject<LoraChannel>(loss, delay);

    MobilityHelper mobEd;
    mobEd.SetPositionAllocator("ns3::UniformDiscPositionAllocator",
                               "rho",
                               DoubleValue(radiusM),
                               "X",
                               DoubleValue(0.0),
                               "Y",
                               DoubleValue(0.0),
                               "Z",
                               DoubleValue(0.0));
    mobEd.SetMobilityModel("ns3::ConstantPositionMobilityModel");

    auto gwPos = CreateObject<ListPositionAllocator>();
    gwPos->Add(Vector(0.0, 0.0, h));
    MobilityHelper mobGw;
    mobGw.SetPositionAllocator(gwPos);
    mobGw.SetMobilityModel("ns3::ConstantPositionMobilityModel");

    LoraPhyHelper phy;
    phy.SetChannel(channel);
    LorawanMacHelper mac;
    LoraHelper helper;
    helper.EnablePacketTracking();

    NodeContainer gateways;
    gateways.Create(1);
    mobGw.Install(gateways);
    phy.SetDeviceType(LoraPhyHelper::GW);
    mac.SetDeviceType(LorawanMacHelper::GW);
    helper.Install(phy, mac, gateways);

    NodeContainer eds;
    eds.Create(nDevices);
    mobEd.Install(eds);
    auto addrGen = CreateObject<LoraDeviceAddressGenerator>(uint8_t(54), uint32_t(1864));
    phy.SetDeviceType(LoraPhyHelper::ED);
    mac.SetDeviceType(LorawanMacHelper::ED_A);
    mac.SetAddressGenerator(addrGen);
    mac.SetRegion(LorawanMacHelper::EU);
    helper.Install(phy, mac, eds);

    PeriodicSenderHelper app;
    app.SetPeriod(Seconds(periodS));
    app.SetPacketSize(appBytes);
    app.Install(eds);

    LorawanMacHelper::SetSpreadingFactorsUp(eds, gateways, channel);

    Ptr<Node> server = CreateObject<Node>();
    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue("5Mbps"));
    p2p.SetChannelAttribute("Delay", StringValue("2ms"));
    P2PGwRegistration_t reg;
    auto c = p2p.Install(server, gateways.Get(0));
    reg.emplace_back(DynamicCast<PointToPointNetDevice>(c.Get(0)), gateways.Get(0));
    NetworkServerHelper ns;
    ns.EnableAdr(false);
    ns.SetGatewaysP2P(reg);
    ns.SetEndDevices(eds);
    ns.Install(server);
    ForwarderHelper fwd;
    fwd.Install(gateways);

    std::ofstream out(csv);
    out << "device,dr,rx_power_dbm,distance_m\n";
    auto gwMob = gateways.Get(0)->GetObject<MobilityModel>();
    for (int i = 0; i < nDevices; ++i)
    {
        auto m = eds.Get(i)
                     ->GetDevice(0)
                     ->GetObject<LoraNetDevice>()
                     ->GetMac()
                     ->GetObject<EndDeviceLorawanMac>();
        auto edMob = eds.Get(i)->GetObject<MobilityModel>();
        out << i << ',' << unsigned(m->GetDataRate()) << ','
            << channel->GetRxPower(14, edMob, gwMob) << ',' << edMob->GetDistanceFrom(gwMob)
            << '\n';
    }

    LoraPacketTracker& tracker = helper.GetPacketTracker();
    Time end = Seconds(periodS * nPeriods);
    Simulator::Stop(end);
    Simulator::Run();
    std::string counts = tracker.CountMacPacketsGlobally(Seconds(0), end);
    Simulator::Destroy();

    double sent = 0;
    double recv = 0;
    std::istringstream(counts) >> sent >> recv;
    std::cout << "RUN altitudeKm=" << altitudeKm << " totalGainDb=" << totalGainDb
              << " beamwidthDeg=" << beamwidthDeg << " nDevices=" << nDevices
              << " rngRun=" << RngSeedManager::GetRun() << " macSent=" << sent
              << " macReceived=" << recv << std::endl;
    return 0;
}
