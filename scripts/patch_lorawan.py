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
print("lorawan receive filter patch applied")
