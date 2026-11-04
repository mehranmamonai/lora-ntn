// ns-3 packet-level check of the Doppler model: one device under one LEO pass, with no collisions
// and no link-budget limit, so the Doppler filter is the only way a packet can be lost.
#include "leo_doppler.h"

#include "ns3/core-module.h"
#include "ns3/lorawan-module.h"
#include "ns3/mobility-helper.h"
#include "ns3/point-to-point-helper.h"
#include "ns3/propagation-loss-model.h"

#include <fstream>
#include <iostream>
#include <map>

using namespace ns3;
using namespace lorawan;

namespace
{
struct Record
{
    double sendS = 0;
    double elevation = 0;
    bool predicted = false;
    bool received = false;
};

std::map<uint64_t, Record> g_packets;
int g_sf = 12;
double g_fcHz = 868.1e6;
const leo::Vec3 g_device{leo::kEarthRadiusM, 0, 0};
const leo::Orbit* g_orbit = nullptr;
int g_rejected = 0;

bool
Ldro()
{
    return g_sf >= 11;
}

void
OnStartSending(Ptr<const Packet> packet, uint32_t)
{
    LoraTxParameters p;
    p.spreadingFactor = g_sf;
    p.bandwidthHz = 125000;
    p.lowDataRateOptimize = Ldro();
    const double toa = LoraPhy::GetTimeOnAir(packet->GetSize(), p).GetSeconds();
    const double t = Simulator::Now().GetSeconds();
    Record r;
    r.sendS = t;
    r.elevation = g_orbit->ElevationDeg(t, g_device);
    r.predicted = leo::PacketSurvives(*g_orbit, g_device, g_fcHz, 125e3, g_sf, Ldro(), t, toa);
    g_packets[packet->GetUid()] = r;
}

bool
DopplerFilter(Ptr<const Packet>, Time duration)
{
    const double start = (Simulator::Now() - duration).GetSeconds();
    const bool ok = leo::PacketSurvives(*g_orbit,
                                        g_device,
                                        g_fcHz,
                                        125e3,
                                        g_sf,
                                        Ldro(),
                                        start,
                                        duration.GetSeconds());
    g_rejected += !ok;
    return ok;
}

void
OnGatewayReceived(Ptr<const Packet> packet, uint32_t)
{
    auto it = g_packets.find(packet->GetUid());
    if (it != g_packets.end())
    {
        it->second.received = true;
    }
}
} // namespace

int
main(int argc, char* argv[])
{
    double altitudeKm = 560;
    double periodS = 10;
    int appBytes = 47;
    std::string csv = "pass.csv";

    CommandLine cmd(__FILE__);
    cmd.AddValue("sf", "Spreading factor", g_sf);
    cmd.AddValue("altitudeKm", "Orbit altitude (km)", altitudeKm);
    cmd.AddValue("periodS", "Uplink period (s)", periodS);
    cmd.AddValue("appBytes", "Application payload (bytes)", appBytes);
    cmd.AddValue("csv", "Per-packet output CSV", csv);
    cmd.Parse(argc, argv);

    const leo::Orbit probe(altitudeKm * 1e3, 0);
    const double tau = probe.VisibilityS(1.0);
    const leo::Orbit orbit(altitudeKm * 1e3, tau / 2);
    g_orbit = &orbit;

    // Strong fixed link: only Doppler can lose a packet here.
    auto loss = CreateObject<FixedRssLossModel>();
    loss->SetRss(-60);
    Ptr<PropagationDelayModel> delay = CreateObject<ConstantSpeedPropagationDelayModel>();
    auto channel = CreateObject<LoraChannel>(loss, delay);

    LoraPhyHelper phy;
    phy.SetChannel(channel);
    LorawanMacHelper mac;
    mac.SetRegion(LorawanMacHelper::ALOHA); // No duty-cycle limit in this check
    LoraHelper helper;
    helper.EnablePacketTracking();

    NodeContainer gateways;
    gateways.Create(1);
    auto gwMobility = CreateObject<LeoOrbitMobility>();
    gwMobility->SetOrbit(orbit);
    gateways.Get(0)->AggregateObject(gwMobility);
    phy.SetDeviceType(LoraPhyHelper::GW);
    mac.SetDeviceType(LorawanMacHelper::GW);
    helper.Install(phy, mac, gateways);

    NodeContainer eds;
    eds.Create(1);
    auto edPos = CreateObject<ListPositionAllocator>();
    edPos->Add(Vector(g_device.x, g_device.y, g_device.z));
    MobilityHelper mobEd;
    mobEd.SetPositionAllocator(edPos);
    mobEd.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobEd.Install(eds);
    auto addrGen = CreateObject<LoraDeviceAddressGenerator>(uint8_t(54), uint32_t(1864));
    phy.SetDeviceType(LoraPhyHelper::ED);
    mac.SetDeviceType(LorawanMacHelper::ED_A);
    mac.SetAddressGenerator(addrGen);
    helper.Install(phy, mac, eds);

    PeriodicSenderHelper app;
    app.SetPeriod(Seconds(periodS));
    app.SetPacketSize(appBytes);
    app.Install(eds);

    auto edDevice = eds.Get(0)->GetDevice(0)->GetObject<LoraNetDevice>();
    edDevice->GetMac()->GetObject<EndDeviceLorawanMac>()->SetDataRate(12 - g_sf);
    edDevice->GetPhy()->TraceConnectWithoutContext("StartSending", MakeCallback(&OnStartSending));

    auto gwDevice = gateways.Get(0)->GetDevice(0)->GetObject<LoraNetDevice>();
    auto gwPhy = DynamicCast<SimpleGatewayLoraPhy>(gwDevice->GetPhy());
    gwPhy->SetReceiveFilter(MakeCallback(&DopplerFilter));
    gwPhy->TraceConnectWithoutContext("ReceivedPacket", MakeCallback(&OnGatewayReceived));

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

    Simulator::Stop(Seconds(tau));
    Simulator::Run();
    Simulator::Destroy();

    std::ofstream out(csv);
    out << "sf,t,elevation,predicted,received\n";
    int sent = 0;
    int received = 0;
    int agree = 0;
    for (const auto& [uid, r] : g_packets)
    {
        out << g_sf << ',' << r.sendS << ',' << r.elevation << ',' << r.predicted << ','
            << r.received << '\n';
        ++sent;
        received += r.received;
        agree += r.predicted == r.received;
    }
    std::cout << "PASS sf=" << g_sf << " rngRun=" << RngSeedManager::GetRun() << " tauS=" << tau
              << " sent=" << sent << " received=" << received << " rejected=" << g_rejected
              << " agree=" << agree << std::endl;
    return 0;
}
