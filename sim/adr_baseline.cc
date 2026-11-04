// Stock ADR reaction time on the ns-3 lorawan module.
// Channel, gateway layout and devices follow src/lorawan/examples/adr-example.cc.
// Records, per device, when and after how many uplinks the data rate first changes.
#include "ns3/core-module.h"
#include "ns3/lorawan-module.h"
#include "ns3/mobility-helper.h"
#include "ns3/point-to-point-helper.h"

#include <cmath>
#include <fstream>
#include <iostream>
#include <sstream>
#include <vector>

using namespace ns3;
using namespace lorawan;

struct DevRec
{
    uint32_t sent = 0;
    double firstChangeS = -1;
    uint32_t sentAtChange = 0;
    int initialDr = -1;
    int firstNewDr = -1;
    int finalDr = -1;
};

static std::vector<DevRec> g_dev;

static void
OnSent(int i, Ptr<const Packet>)
{
    g_dev[i].sent++;
}

static void
OnDr(int i, uint8_t, uint8_t newDr)
{
    if (Simulator::Now() > Seconds(0) && g_dev[i].firstChangeS < 0)
    {
        g_dev[i].firstChangeS = Simulator::Now().GetSeconds();
        g_dev[i].sentAtChange = g_dev[i].sent;
        g_dev[i].firstNewDr = newDr;
    }
}

int
main(int argc, char* argv[])
{
    int nDevices = 100;
    double periodS = 300;
    int nPeriods = 30;
    double sideM = 10000;
    int gwDistM = 5000;
    double maxRandomLossDb = 10;
    std::string csv = "devices.csv";

    CommandLine cmd(__FILE__);
    cmd.AddValue("nDevices", "Number of end devices", nDevices);
    cmd.AddValue("periodS", "Uplink period (s)", periodS);
    cmd.AddValue("nPeriods", "Number of app periods to simulate", nPeriods);
    cmd.AddValue("HistoryRange", "ns3::AdrComponent::HistoryRange");
    cmd.AddValue("csv", "Per-device output CSV", csv);
    cmd.Parse(argc, argv);

    Config::SetDefault("ns3::EndDeviceLorawanMac::ADR", BooleanValue(true));

    auto loss = CreateObject<LogDistancePropagationLossModel>();
    loss->SetPathLossExponent(3.76);
    loss->SetReference(1, 7.7);
    auto x = CreateObject<UniformRandomVariable>();
    x->SetAttribute("Min", DoubleValue(0.0));
    x->SetAttribute("Max", DoubleValue(maxRandomLossDb));
    auto randomLoss = CreateObject<RandomPropagationLossModel>();
    randomLoss->SetAttribute("Variable", PointerValue(x));
    loss->SetNext(randomLoss);
    Ptr<PropagationDelayModel> delay = CreateObject<ConstantSpeedPropagationDelayModel>();
    auto channel = CreateObject<LoraChannel>(loss, delay);

    int rings = 2 + (std::sqrt(2) * sideM) / gwDistM;
    int nGateways = 3 * rings * rings - 3 * rings + 1;

    MobilityHelper mobEd;
    MobilityHelper mobGw;
    mobEd.SetPositionAllocator(
        "ns3::RandomRectanglePositionAllocator",
        "X",
        PointerValue(CreateObjectWithAttributes<UniformRandomVariable>("Min",
                                                                       DoubleValue(-sideM),
                                                                       "Max",
                                                                       DoubleValue(sideM))),
        "Y",
        PointerValue(CreateObjectWithAttributes<UniformRandomVariable>("Min",
                                                                       DoubleValue(-sideM),
                                                                       "Max",
                                                                       DoubleValue(sideM))));
    mobEd.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobGw.SetPositionAllocator(CreateObject<HexGridPositionAllocator>(gwDistM / 2));
    mobGw.SetMobilityModel("ns3::ConstantPositionMobilityModel");

    LoraPhyHelper phy;
    phy.SetChannel(channel);
    LorawanMacHelper mac;
    LoraHelper helper;
    helper.EnablePacketTracking();

    NodeContainer gateways;
    gateways.Create(nGateways);
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
    app.Install(eds);

    Ptr<Node> server = CreateObject<Node>();
    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue("5Mbps"));
    p2p.SetChannelAttribute("Delay", StringValue("2ms"));
    P2PGwRegistration_t reg;
    for (auto gw = gateways.Begin(); gw != gateways.End(); ++gw)
    {
        auto c = p2p.Install(server, *gw);
        reg.emplace_back(DynamicCast<PointToPointNetDevice>(c.Get(0)), *gw);
    }
    NetworkServerHelper ns;
    ns.EnableAdr(true);
    ns.SetAdr("ns3::AdrComponent");
    ns.SetGatewaysP2P(reg);
    ns.SetEndDevices(eds);
    ns.Install(server);
    ForwarderHelper fwd;
    fwd.Install(gateways);

    g_dev.resize(nDevices);
    std::vector<Ptr<EndDeviceLorawanMac>> macs;
    for (int i = 0; i < nDevices; ++i)
    {
        auto m = eds.Get(i)
                     ->GetDevice(0)
                     ->GetObject<LoraNetDevice>()
                     ->GetMac()
                     ->GetObject<EndDeviceLorawanMac>();
        macs.push_back(m);
        g_dev[i].initialDr = m->GetDataRate();
        m->TraceConnectWithoutContext("SentNewPacket", MakeBoundCallback(&OnSent, i));
        m->TraceConnectWithoutContext("DataRate", MakeBoundCallback(&OnDr, i));
    }

    LoraPacketTracker& tracker = helper.GetPacketTracker();
    Time end = Seconds(periodS * nPeriods);
    Simulator::Stop(end);
    Simulator::Run();
    for (int i = 0; i < nDevices; ++i)
    {
        g_dev[i].finalDr = macs[i]->GetDataRate();
    }
    std::string counts = tracker.CountMacPacketsGlobally(Seconds(0), end);
    Simulator::Destroy();

    std::ofstream out(csv);
    out << "device,sent,first_change_s,sent_at_change,initial_dr,first_new_dr,final_dr\n";
    for (int i = 0; i < nDevices; ++i)
    {
        const auto& d = g_dev[i];
        out << i << ',' << d.sent << ',' << d.firstChangeS << ',' << d.sentAtChange << ','
            << d.initialDr << ',' << d.firstNewDr << ',' << d.finalDr << '\n';
    }
    double sent = 0;
    double recv = 0;
    std::istringstream(counts) >> sent >> recv;
    std::cout << "RUN nDevices=" << nDevices << " periodS=" << periodS << " nPeriods=" << nPeriods
              << " nGateways=" << nGateways << " rngRun=" << RngSeedManager::GetRun()
              << " macSent=" << sent << " macReceived=" << recv << " pdr=" << recv / sent
              << std::endl;
    return 0;
}
