# DIAMETER Support with SMC

This document lists the AVPs used and not used by the Session Management Controller (SMC) when communicating to other Diameter peers, organized per Diameter application.

> [!NOTE]
> All mandatory AVPs, such as `Session-Id` or `Origin-Host`, are supported in the applications listed below.

## DIAMETER Applications

The following AVP types from the base 3GPP Diameter dictionary are used:

| AVP | Code | Type | Flags |
| ------------------------------- | ---: | -----------: | :------: |
| 3GPP-IMSI | 1 | UTF8String | V |
| 3GPP-Charging-Id | 2 | Unsigned32 | V |
| 3GPP-PDP-Type | 3 | Enumerated | V |
| 3GPP-SGSN-Address | 6 | OctetString | V |
| 3GPP-GGSN-Address | 7 | OctetString | V |
| 3GPP-IMSI-MCC-MNC | 8 | UTF8String | V |
| 3GPP-NSAPI | 10 | OctetString | V |
| 3GPP-Selection-Mode | 12 | UTF8String | V |
| 3GPP-SGSN-IPv6-Address | 15 | OctetString | V |
| 3GPP-GGSN-IPv6-Address | 16 | OctetString | V |
| 3GPP-SGSN-MCC-MNC | 18 | UTF8String | V |
| 3GPP-IMEISV | 20 | OctetString | V |
| 3GPP-RAT-Type | 21 | OctetString | V |
| 3GPP-User-Location-Info | 22 | OctetString | V |
| 3GPP-MS-TimeZone | 23 | OctetString | V |

The following AVP types from the base 3GPP Diameter dictionary are not used:

| AVP | Code | Type | Flags |
| ------------------------------- | ---: | -----------: | :------: |
| 3GPP-CG-Address | 4 | OctetString | V |
| 3GPP-Session-Stop-Indicator | 11 | OctetString | V |
| 3GPP-CG-IPv6-Address | 14 | OctetString | V |
| 3GPP-CAMEL-Charging-Info | 24 | OctetString | V |
| 3GPP-Packet-Filter | 25 | OctetString | V |
| 3GPP-Negotiated-DSCP | 26 | OctetString | V |
| 3GPP-Allocate-IP-Type | 27 | OctetString | V |

### Authentication via NASREQ

The following dictionaries are used in the NASREQ application:

- Base Diameter (RFC 6733)
- NASREQ Application (RFC 4005)
- Credit-Control Application (RFC 4006)
- Custom vendor AVPs (vendor 99999, id 1). The following AVP types are used:

| AVP | Vendor | Code | Type | Flags |
| -------------------------------- | ------ | ---: | -----------: | :------: |
| Accounting-Input-Octets | 0 | 363 | Unsigned64 | M |
| Accounting-Input-Packets | 0 | 365 | Unsigned64 | M |
| Accounting-Output-Octets | 0 | 364 | Unsigned64 | M |
| Accounting-Output-Packets | 0 | 366 | Unsigned64 | M |
| Accounting-Record-Number | 0 | 485 | Unsigned32 | M |
