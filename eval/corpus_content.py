"""Content of the synthetic evaluation corpus. Everything here is fictional.

The corpus is designed, not sampled: it deliberately contains repeated
sub-headings (several "Warranty", "Repair", "Deposits" sections), facts that
only make sense with their heading ("Coverage: 8 years"), and exact
identifiers (codes, bulletin numbers). That stresses section disambiguation,
which is what structure-aware retrieval claims to fix, so results on it say
how the modes differ on that kind of document and nothing about every corpus.

Each document is a tree: (heading, text, [children]).
"""

MANUAL = ("Voltra E5 Owner's Manual", "", [
    ("1 Getting Started", "This manual covers the Voltra E5 electric hatchback, model years 2026 and 2027.", [
        ("1.1 Keys and Access", "The E5 ships with two card keys and one key fob. Hold a card key against the B-pillar "
         "reader to unlock. The fob unlocks the car when you are within two metres and a door handle is touched. "
         "If the fob battery is flat, place the fob in the cup holder to start the car.", []),
        ("1.2 Driver Display", "The 10.25-inch driver display shows speed, range and active warnings. Swipe the left "
         "steering-wheel pad to switch between the Range, Energy and Trip views.", []),
        ("1.3 Seat Adjustment", "Front seats adjust electrically in eight directions. The driver seat stores three "
         "memory positions linked to each key.", []),
    ]),
    ("2 Charging", "The E5 accepts AC charging up to 11 kW and DC fast charging up to 150 kW.", [
        ("2.1 Home Charging", "With an 11 kW wall box a full charge from empty takes about 7.5 hours. On a standard "
         "household socket using the portable charger the same charge takes about 38 hours. Set the charging current "
         "limit in Settings > Charging if your home circuit is shared.", []),
        ("2.2 Public DC Fast Charging", "Peak DC power is 150 kW. Charging from 10 to 80 percent takes about 28 minutes "
         "when the battery is at operating temperature. Use Battery Preconditioning before arriving at a fast charger "
         "in cold weather.", []),
        ("2.3 Scheduled Charging", "Scheduled charging starts the session at a chosen time, for example to use "
         "off-peak electricity tariffs. A departure time can be set instead, and the car will finish charging and warm "
         "the cabin by then.", []),
        ("2.4 Charging Port Light", "The ring around the charging port changes colour to show charging status.\n\n"
         "| Colour | Meaning |\n|---|---|\n| White | Port open, ready to connect |\n| Pulsing green | Charging |\n"
         "| Solid green | Charging complete |\n| Amber | Charging fault, see warning code |\n"
         "| Blue | Scheduled charging is waiting to start |", []),
    ]),
    ("3 Driving", "", [
        ("3.1 Drive Modes", "Eco limits power to 110 kW and softens accelerator response to extend range. Normal gives "
         "the full 160 kW. Sport sharpens steering weight and throttle response. Snow reduces torque at the front "
         "axle to limit wheel spin.", []),
        ("3.2 Regenerative Braking", "Regeneration has four levels, 0 to 3. Level 3 enables one-pedal driving and can "
         "bring the car to a full stop. Regeneration is reduced automatically when the battery is full or very "
         "cold.", []),
        ("3.3 Towing", "The E5 may tow a braked trailer of up to 1,200 kg or an unbraked trailer of up to 750 kg. "
         "Maximum vertical load on the tow ball is 75 kg. Expect range to fall by 30 to 40 percent while towing.", []),
    ]),
    ("4 High-Voltage Battery", "The 77 kWh lithium-ion battery sits under the cabin floor.", [
        ("4.1 Battery Care", "For daily use set the charge limit to 80 percent. Charge to 100 percent only before long "
         "trips. Avoid leaving the car below 10 percent for long periods.", []),
        ("4.2 Storage", "If the car will be parked for more than a month, leave it at 50 to 60 percent charge and "
         "check the charge level every three months.", []),
        ("4.3 Warranty", "Coverage: 8 years or 160,000 km, whichever comes first. The battery is covered against "
         "capacity falling below 70 percent of its original capacity during this period.", []),
    ]),
    ("5 Maintenance", "", [
        ("5.1 Service Schedule", "Have the car serviced every 24 months or 30,000 km, whichever comes first. Each "
         "service includes a brake inspection, coolant check and software update.", []),
        ("5.2 Tyres", "Recommended cold tyre pressure is 2.5 bar at the front and 2.7 bar at the rear. Rotate the "
         "tyres every 10,000 km. Replace a tyre when tread depth falls below 3 mm.", []),
        ("5.3 Brake Fluid", "Replace the brake fluid every 2 years regardless of distance driven.", []),
        ("5.4 Cabin Air Filter", "Replace the cabin air filter every 12 months. In dusty climates replace it every "
         "6 months.", []),
        ("5.5 12V Battery", "A conventional 12V battery powers locks, lights and the infotainment system. Its "
         "expected life is about 4 years. If it is flat the car cannot be unlocked with the card key; use the "
         "mechanical key hidden in the fob.", []),
    ]),
    ("6 Warranty", "Warranty starts on the date of first registration.", [
        ("6.1 Basic Vehicle Warranty", "Coverage: 3 years or 100,000 km, whichever comes first. Covers defects in "
         "materials and workmanship of the vehicle.", []),
        ("6.2 Drive Unit", "Coverage: 6 years or 150,000 km, whichever comes first. Covers the electric motors, "
         "inverters and reduction gears.", []),
        ("6.3 Paint and Corrosion", "Paint defects are covered for 3 years. Rust perforation of body panels from "
         "the inside out is covered for 12 years with no distance limit.", []),
        ("6.4 Exclusions", "Warranty does not cover tyres, wiper blades, brake pads, damage from accidents, or "
         "damage caused by fitting non-approved accessories.", []),
    ]),
    ("7 Warning Codes", "Warning codes appear on the driver display and in the Voltra app.", [
        ("7.1 Charging Codes", "| Code | Meaning | Action |\n|---|---|---|\n"
         "| E-201 | Charging cable not locked | Reinsert the connector until it clicks |\n"
         "| E-204 | Charging port overheated | Stop charging and let the port cool for 30 minutes |\n"
         "| E-207 | Charger communication lost | Try another charger; if it repeats, contact service |\n"
         "| E-210 | Ground fault at the charger | Do not charge from this socket; have it inspected |", []),
        ("7.2 Drivetrain Codes", "| Code | Meaning | Action |\n|---|---|---|\n"
         "| D-301 | Motor temperature high | Drive gently; power is limited until it cools |\n"
         "| D-305 | Inverter fault | Stop safely and call roadside assistance |\n"
         "| D-312 | Gear selector fault | Park the car and contact service |", []),
        ("7.3 Battery Codes", "| Code | Meaning | Action |\n|---|---|---|\n"
         "| B-401 | Battery temperature high | Stop and let the battery cool before driving on |\n"
         "| B-406 | Cell imbalance detected | Charge to 100 percent once; if it repeats, contact service |\n"
         "| B-415 | Insulation fault | Stop safely, leave the vehicle and call roadside assistance |", []),
    ]),
])

TSBS = [
    ("TSB-2026-007", "Door handle does not extend", "E5 built January to March 2026",
     "One or more flush door handles stay retracted when the car is unlocked in temperatures below minus 5 degrees.",
     "Ice forms around the handle actuator because the drain channel is too narrow.",
     "Replace the handle actuator seal with part 5DH-220 and widen the drain channel using tool T-41.", "0.8 hours"),
    ("TSB-2026-011", "Slow DC charging in cold weather", "All E5 with software below 3.2",
     "DC charging power stays below 50 kW in cold weather even after preconditioning.",
     "The battery heater target temperature is set too low in early software.",
     "Update the vehicle software to version 3.2 or later.", "0.5 hours"),
    ("TSB-2026-014", "Rattle from rear parcel shelf", "E5 hatchback, all build dates",
     "A rattle is heard from the rear parcel shelf on rough roads.",
     "The shelf hinge clips loosen over time.",
     "Fit two felt pads, part 5PS-018, under the hinge clips and replace the clips with part 5PS-019.", "0.3 hours"),
    ("TSB-2026-019", "Infotainment screen reboots", "E5 with head unit hardware revision B",
     "The centre screen goes black and restarts while driving, typically after 40 minutes.",
     "A memory leak in the navigation map service.",
     "Update the head unit firmware to version 7.4.1.", "0.4 hours"),
    ("TSB-2026-023", "Coolant smell in cabin", "E5 built before May 2026",
     "A sweet smell is noticed in the cabin after the heat pump runs for a long time.",
     "A hose clamp on the cabin heater core can loosen and weep coolant.",
     "Replace the clamp with spring clamp part 5HC-301 and top up coolant to the MAX mark.", "1.2 hours"),
    ("TSB-2026-027", "Tailgate does not close fully", "E5 with power tailgate",
     "The power tailgate stops a few centimetres before closing and reopens.",
     "The anti-pinch sensor strip is too sensitive after a production calibration error.",
     "Recalibrate the anti-pinch sensor with diagnostic routine TG-CAL-2.", "0.5 hours"),
    ("TSB-2026-031", "Wind noise from driver window", "E5 built February to June 2026",
     "Wind noise from the top of the driver's window above 90 km/h.",
     "The upper window seal was fitted out of position at the factory.",
     "Refit the upper seal using alignment gauge T-55; replace the seal (part 5WS-112) if it is deformed.",
     "0.7 hours"),
    ("TSB-2026-036", "Phone key not recognised", "All E5 with app version below 5.0",
     "The car does not unlock when approached with a phone key, although the app shows it is connected.",
     "A Bluetooth pairing token is not refreshed after phone operating system updates.",
     "Ask the customer to update the Voltra app to 5.0 or later, then delete and re-pair the phone key.",
     "0.2 hours"),
]

HANDBOOK = ("Dealer Operations Handbook", "Applies to all Voltra-authorised dealerships from 1 July 2026.", [
    ("Vehicle Sales", "", [
        ("Deposits", "A domestic order deposit is 10 percent of the vehicle price. The deposit is fully refundable "
         "within 7 days of payment; after that it is refunded minus a 500 dirham administration fee.", []),
        ("Test Drives", "Customers must hold a full driving licence for at least 2 years. Test drives last up to 30 "
         "minutes and a sales consultant must ride along. Overnight test drives need sales manager approval.", []),
        ("Trade-Ins", "A trade-in valuation is valid for 14 days or 500 km, whichever comes first. Vehicles older "
         "than 10 years are accepted only for scrap value.", []),
        ("Financing", "Finance is arranged through partner banks. Minimum down payment is 20 percent and the "
         "longest term offered is 60 months.", []),
    ]),
    ("Returns and Cancellations", "", [
        ("Cooling-Off Period", "A customer may return a new vehicle within 5 days of delivery if it has been driven "
         "less than 300 km and is undamaged.", []),
        ("Exceptions", "Cooling-off does not apply to custom-ordered colours, fleet orders, or vehicles registered "
         "for export.", []),
        ("Refund Processing", "Refunds are paid to the original payment method within 10 business days of the "
         "vehicle being returned and inspected.", []),
    ]),
    ("Export Sales", "Export sales follow the Export Shipping Guide in addition to this section.", [
        ("Deposits", "Export orders require a 30 percent deposit, which is non-refundable once the vehicle has been "
         "allocated to the order.", []),
        ("Documentation", "The dealership prepares the commercial invoice and requests the export certificate. "
         "The customer supplies a copy of their passport and the consignee's details.", []),
        ("Lead Times", "Allow 3 weeks from full payment to vessel loading for RoRo shipments and 4 weeks for "
         "containers.", []),
    ]),
    ("Customer Data", "", [
        ("Retention", "Customer records are kept for 6 years after the last transaction, then deleted.", []),
        ("Access Requests", "Respond to a customer's request for a copy of their data within 30 days.", []),
        ("Marketing Consent", "Marketing messages may be sent only to customers who opted in. Record the date "
         "and channel of the consent.", []),
    ]),
    ("Workshop", "", [
        ("Opening Hours", "Workshops open 7:30 to 19:00 Saturday to Thursday and are closed on Friday.", []),
        ("Courtesy Cars", "A courtesy car is offered when a repair is expected to take more than 4 hours. The "
         "customer must hold a licence for at least 2 years.", []),
        ("Warranty Claims", "Submit warranty claims to Voltra within 14 days of the repair, with photos of the "
         "failed part and the diagnostic report.", []),
    ]),
])

COUNTRIES = [
    ("Arland", "8 years", "Left-hand drive only", "Pre-shipment inspection by an approved agency is required.",
     "Import duty is 5 percent of the CIF value."),
    ("Borovia", "5 years", "Left-hand drive only", "Inspection on arrival at the port of entry; no pre-shipment check.",
     "Import duty is 20 percent; electric vehicles are exempt."),
    ("Cestria", "No age limit", "Left- or right-hand drive", "Pre-shipment roadworthiness certificate required.",
     "Import duty is 25 percent, plus 5 percent excise for vehicles above 3 tonnes."),
    ("Dunmark", "3 years", "Right-hand drive only", "Pre-shipment inspection including radiation screening.",
     "Import duty is 10 percent of the CIF value."),
]

GUIDE = ("Vehicle Export Shipping Guide", "This guide explains how dealerships ship vehicles to overseas buyers.", [
    ("1 Documentation", "Every export shipment needs the documents below before the vehicle reaches the port.", [
        ("1.1 Export Certificate", "The export certificate cancels the local registration. Apply through the "
         "traffic authority at least 5 working days before shipping. It costs 200 dirhams.", []),
        ("1.2 Bill of Lading", "The shipping line issues the bill of lading after loading. The original must be "
         "couriered to the buyer, or a telex release requested.", []),
        ("1.3 Certificate of Origin", "Issued by the chamber of commerce within 2 working days; it is required by "
         "Borovia and Dunmark.", []),
    ]),
    ("2 Shipping Methods", "", [
        ("2.1 RoRo", "Roll-on/roll-off is the cheapest method. The vehicle must be driveable and must not carry "
         "personal belongings. Typical transit to the Arland port is 12 days.", []),
        ("2.2 Container", "A 40-foot container holds up to four cars. Container shipping allows personal items in "
         "the cabin and suits damaged or non-running vehicles.", []),
        ("2.3 Air Freight", "Air freight is used only for urgent, high-value orders. The battery must be at or "
         "below 30 percent charge for electric vehicles.", []),
    ]),
    ("3 Destination Requirements", "Rules change often; confirm with the destination agent before allocating a "
     "vehicle.", [
        (f"3.{i} {name}", "", [
            (f"3.{i}.1 Age Limit", f"Maximum vehicle age: {age}.", []),
            (f"3.{i}.2 Steering", f"{steer}.", []),
            (f"3.{i}.3 Inspection", insp, []),
            (f"3.{i}.4 Duty", duty, []),
        ]) for i, (name, age, steer, insp, duty) in enumerate(COUNTRIES, 1)
    ]),
])
