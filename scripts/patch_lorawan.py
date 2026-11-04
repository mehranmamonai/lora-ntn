"""Add a receive filter to SimpleGatewayLoraPhy so scenarios can drop packets (e.g. Doppler).

Idempotent. A packet the filter rejects has still occupied a demodulator and caused interference.
"""
import pathlib
import sys

model = pathlib.Path(sys.argv[1]) / "src/lorawan/model"
header = model / "simple-gateway-lora-phy.h"
source = model / "simple-gateway-lora-phy.cc"

h = header.read_text()
if "SetReceiveFilter" not in h:
    anchor = "  private:\n    // Implementation of GatewayLoraPhy's pure virtual function\n    void EndReceive"
    assert anchor in h
    h = h.replace(
        anchor,
        "    /** Set a callback that may reject a packet at the end of reception. */\n"
        "    void SetReceiveFilter(Callback<bool, Ptr<const Packet>, Time> filter)\n"
        "    {\n"
        "        m_receiveFilter = filter;\n"
        "    }\n\n"
        + anchor,
    )
    anchor2 = "void EndReceive(Ptr<Packet> packet, Ptr<LoraInterferenceHelper::Event> event) override;\n"
    assert anchor2 in h
    h = h.replace(
        anchor2,
        anchor2 + "\n    Callback<bool, Ptr<const Packet>, Time> m_receiveFilter; //!< Optional reception filter\n",
    )
    header.write_text(h)

s = source.read_text()
if "m_receiveFilter" not in s:
    anchor = '    NS_LOG_INFO("Packet with SF " << unsigned(event->GetSpreadingFactor())\n'
    assert anchor in s
    s = s.replace(
        anchor,
        "    if (!m_receiveFilter.IsNull() && !m_receiveFilter(packet, event->GetDuration()))\n"
        "    {\n"
        '        NS_LOG_DEBUG("Packet rejected by the receive filter");\n'
        "        return;\n"
        "    }\n\n" + anchor,
    )
    source.write_text(s)

# Selectable LDRO threshold on end devices. The default of 11 keeps LoRaWAN's behaviour.
mac_h = model / "class-a-end-device-lorawan-mac.h"
mac_c = model / "class-a-end-device-lorawan-mac.cc"
text = mac_h.read_text()
if "s_ldroMinSf" not in text:
    anchor = "class ClassAEndDeviceLorawanMac : public EndDeviceLorawanMac\n{\n  public:\n"
    assert anchor in text
    mac_h.write_text(text.replace(
        anchor,
        anchor + "    static uint8_t s_ldroMinSf; //!< Lowest SF using LDRO at 125 kHz\n\n",
    ))
text = mac_c.read_text()
if "s_ldroMinSf" not in text:
    a1 = "NS_OBJECT_ENSURE_REGISTERED(ClassAEndDeviceLorawanMac);\n"
    a2 = "auto ldro = bool((sf == 11 || sf == 12) && bw == 125'000);"
    assert a1 in text and a2 in text
    text = text.replace(a1, a1 + "\nuint8_t ClassAEndDeviceLorawanMac::s_ldroMinSf = 11;\n")
    text = text.replace(a2, "auto ldro = bool(sf >= s_ldroMinSf && bw == 125'000);")
    mac_c.write_text(text)

# Speed-up for large networks: uplinks need not be delivered to other end devices.
# Off by default. Their effect on device downlink reception is then not modelled.
ch_h = model / "lora-channel.h"
ch_c = model / "lora-channel.cc"
text = ch_h.read_text()
if "s_uplinkOnlyToGateways" not in text:
    a1 = "    void Add(Ptr<LoraPhy> phy);\n"
    a2 = "    std::vector<Ptr<LoraPhy>> m_phyList;\n"
    assert a1 in text and a2 in text
    text = text.replace(a1, "    static bool s_uplinkOnlyToGateways; //!< Skip uplink delivery to end devices\n\n" + a1)
    text = text.replace(a2, a2 + "    std::vector<Ptr<LoraPhy>> m_gwPhyList; //!< Gateway PHYs only\n")
    ch_h.write_text(text)
text = ch_c.read_text()
if "s_uplinkOnlyToGateways" not in text:
    a1 = "    // Add the new phy to the vector\n    m_phyList.push_back(phy);\n"
    assert a1 in text
    text = text.replace(
        a1,
        a1 + "    if (DynamicCast<GatewayLoraPhy>(phy))\n    {\n        m_gwPhyList.push_back(phy);\n    }\n",
    )
    start = text.index("LoraChannel::Send(")
    a2 = "for (const auto& receiver : m_phyList)"
    pos = text.index(a2, start)
    text = (text[:pos]
            + "const auto& targets =\n"
              "        (s_uplinkOnlyToGateways && DynamicCast<EndDeviceLoraPhy>(sender)) ? m_gwPhyList : m_phyList;\n"
              "    for (const auto& receiver : targets)"
            + text[pos + len(a2):])
    first_ns = text.index("NS_OBJECT_ENSURE_REGISTERED(LoraChannel);\n")
    marker = "NS_OBJECT_ENSURE_REGISTERED(LoraChannel);\n"
    text = (text[:first_ns + len(marker)] + "\nbool LoraChannel::s_uplinkOnlyToGateways = false;\n"
            + text[first_ns + len(marker):])
    first_include = text.index("#include")
    text = (text[:first_include] + '#include "end-device-lora-phy.h"\n#include "gateway-lora-phy.h"\n'
            + text[first_include:])
    ch_c.write_text(text)
print("lorawan patches applied")
