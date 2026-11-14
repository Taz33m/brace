"""Real source text used by the hazards tests. Not a test module itself.

ADVISORY_35 / ADVISORY_39: complete NHC Forecast/Advisories 35 and 39 for Hurricane Beryl
(AL022024), copied from https://www.nhc.noaa.gov/archive/2024/al02/.
RFW_*: NWS Los Angeles/Oxnard Red Flag Warning products from January 2025 (Iowa Environmental
Mesonet archive). Each keeps the product header and two of its zone segments, and each segment
is cut off before its RELATIVE HUMIDITY bullet. Apart from trailing spaces, the kept text is unaltered.
"""

ADVISORY_35 = """
ZCZC MIATCMAT2 ALL
TTAA00 KNHC DDHHMM

TROPICAL STORM BERYL FORECAST/ADVISORY NUMBER  35
NWS NATIONAL HURRICANE CENTER MIAMI FL       AL022024
0900 UTC SUN JUL 07 2024

TROPICAL STORM CENTER LOCATED NEAR 25.3N  94.6W AT 07/0900Z
POSITION ACCURATE WITHIN  20 NM

PRESENT MOVEMENT TOWARD THE NORTHWEST OR 320 DEGREES AT  10 KT

ESTIMATED MINIMUM CENTRAL PRESSURE  995 MB
MAX SUSTAINED WINDS  50 KT WITH GUSTS TO  60 KT.
50 KT....... 40NE   0SE   0SW  40NW.
34 KT.......110NE  40SE  40SW  90NW.
12 FT SEAS..105NE  60SE  75SW  60NW.
WINDS AND SEAS VARY GREATLY IN EACH QUADRANT.  RADII IN NAUTICAL
MILES ARE THE LARGEST RADII EXPECTED ANYWHERE IN THAT QUADRANT.

REPEAT...CENTER LOCATED NEAR 25.3N  94.6W AT 07/0900Z
AT 07/0600Z CENTER WAS LOCATED NEAR 24.9N  94.3W

FORECAST VALID 07/1800Z 26.3N  95.4W
MAX WIND  60 KT...GUSTS  75 KT.
50 KT... 40NE  30SE   0SW  40NW.
34 KT...100NE  60SE  40SW  80NW.

FORECAST VALID 08/0600Z 28.1N  96.1W
MAX WIND  75 KT...GUSTS  90 KT.
64 KT... 20NE  20SE   0SW   0NW.
50 KT... 40NE  40SE  25SW  40NW.
34 KT...100NE  90SE  50SW  70NW.

FORECAST VALID 08/1800Z 30.2N  96.1W...INLAND
MAX WIND  45 KT...GUSTS  55 KT.
34 KT... 50NE  90SE  40SW  50NW.

FORECAST VALID 09/0600Z 32.5N  95.1W...INLAND
MAX WIND  30 KT...GUSTS  40 KT.

FORECAST VALID 09/1800Z 34.7N  93.3W...POST-TROP/INLAND
MAX WIND  25 KT...GUSTS  35 KT.

FORECAST VALID 10/0600Z 36.7N  91.6W...POST-TROP/INLAND
MAX WIND  20 KT...GUSTS  30 KT.

EXTENDED OUTLOOK. NOTE...ERRORS FOR TRACK HAVE AVERAGED NEAR 125 NM
ON DAY 4 AND 175 NM ON DAY 5...AND FOR INTENSITY NEAR 15 KT EACH DAY

OUTLOOK VALID 11/0600Z 40.5N  87.0W...POST-TROP/INLAND
MAX WIND  20 KT...GUSTS  30 KT.

OUTLOOK VALID 12/0600Z 43.5N  83.5W...POST-TROP/INLAND
MAX WIND  20 KT...GUSTS  30 KT.

REQUEST FOR 3 HOURLY SHIP REPORTS WITHIN 300 MILES OF 25.3N  94.6W

INTERMEDIATE PUBLIC ADVISORY...WTNT32 KNHC/MIATCPAT2...AT 07/1200Z

NEXT ADVISORY AT 07/1500Z

$$
FORECASTER PAPIN


NNNN
"""

ADVISORY_39 = """
ZCZC MIATCMAT2 ALL
TTAA00 KNHC DDHHMM

HURRICANE BERYL FORECAST/ADVISORY NUMBER  39
NWS NATIONAL HURRICANE CENTER MIAMI FL       AL022024
0900 UTC MON JUL 08 2024

HURRICANE CENTER LOCATED NEAR 28.6N  96.0W AT 08/0900Z
POSITION ACCURATE WITHIN  20 NM

PRESENT MOVEMENT TOWARD THE NORTH OR 355 DEGREES AT  10 KT

ESTIMATED MINIMUM CENTRAL PRESSURE  979 MB
MAX SUSTAINED WINDS  70 KT WITH GUSTS TO  85 KT.
64 KT....... 40NE  40SE   0SW   0NW.
50 KT....... 60NE  60SE  30SW  30NW.
34 KT.......100NE 100SE  60SW  80NW.
12 FT SEAS..105NE 120SE  60SW   0NW.
WINDS AND SEAS VARY GREATLY IN EACH QUADRANT.  RADII IN NAUTICAL
MILES ARE THE LARGEST RADII EXPECTED ANYWHERE IN THAT QUADRANT.

REPEAT...CENTER LOCATED NEAR 28.6N  96.0W AT 08/0900Z...ON COAST
AT 08/0600Z CENTER WAS LOCATED NEAR 28.2N  95.9W

FORECAST VALID 08/1800Z 30.4N  95.8W...INLAND
MAX WIND  55 KT...GUSTS  65 KT.
50 KT... 30NE  30SE   0SW   0NW.
34 KT... 50NE  90SE  30SW  30NW.

FORECAST VALID 09/0600Z 32.7N  94.4W...INLAND
MAX WIND  35 KT...GUSTS  45 KT.
34 KT... 30NE  30SE   0SW   0NW.

FORECAST VALID 09/1800Z 35.0N  92.1W...INLAND
MAX WIND  25 KT...GUSTS  35 KT.

FORECAST VALID 10/0600Z 37.5N  89.0W...POST-TROP/INLAND
MAX WIND  20 KT...GUSTS  30 KT.

FORECAST VALID 10/1800Z 40.0N  85.8W...POST-TROP/INLAND
MAX WIND  20 KT...GUSTS  30 KT.

FORECAST VALID 11/0600Z 42.0N  83.0W...POST-TROP/INLAND
MAX WIND  20 KT...GUSTS  30 KT.

EXTENDED OUTLOOK. NOTE...ERRORS FOR TRACK HAVE AVERAGED NEAR 125 NM
ON DAY 4 AND 175 NM ON DAY 5...AND FOR INTENSITY NEAR 15 KT EACH DAY

OUTLOOK VALID 12/0600Z...DISSIPATED

REQUEST FOR 3 HOURLY SHIP REPORTS WITHIN 300 MILES OF 28.6N  96.0W

INTERMEDIATE PUBLIC ADVISORY...WTNT32 KNHC/MIATCPAT2...AT 08/1200Z

NEXT ADVISORY AT 08/1500Z

$$
FORECASTER BEVEN


NNNN
"""

RFW_JAN5_2240Z = """700
WWUS86 KLOX 052240
RFWLOX

URGENT - FIRE WEATHER MESSAGE
National Weather Service Los Angeles/Oxnard CA
240 PM PST Sun Jan 5 2025

...WIDESPREAD DAMAGING NORTH TO NORTHEAST WINDS AND LONG DURATION
OF RED FLAG CONDITIONS LIKELY OVER MANY PORTIONS OF LOS ANGELES
AND VENTURA COUNTIES BETWEEN TUESDAY AND THURSDAY -- POSSIBLY
EXTENDING INTO FRIDAY...

...RED FLAG WARNING IN EFFECT FOR MUCH OF LOS ANGELES COUNTY AND
SOUTHERN VENTURA COUNTY MOUNTAINS/EASTERN VENTURA COUNTY VALLEYS
FROM 10 AM TUESDAY TO 6 PM THURSDAY -- FIRE WEATHER WATCHES REMAIN
THURSDAY NIGHT INTO FRIDAY...

...FIRE WEATHER WATCH REMAINS IN EFFECT FOR VENTURA COUNTY COASTAL
PLAIN AND NORTHERN VENTURA MOUNTAINS FROM 10 AM TUESDAY TO 6 PM
FRIDAY...

...FIRE WEATHER WATCH REMAINS IN EFFECT FROM 6 PM TUESDAY TO 8 PM
WEDNESDAY FOR THE LOS ANGELES COAST, PALOS VERDES, AND CATALINA
ISLAND...

.While there is still some uncertainty in this week's strong wind
event and corresponding humidity levels at the onset, there is
growing confidence for a widespread strong/damaging north to
northeast wind event with an extended period of dangerous Red
Flag conditions. While the longer duration of strong winds is
expected to be focused across Los Angeles and Ventura counties,
there is a 20-30 percent chance of shorter duration Red Flag
conditions across portions of Santa Barbara and San Luis Obispo
counties.

With widespread damaging winds likely from Tuesday afternoon into
Wednesday across portions of Los Angeles and Ventura counties,
there will be an increased risk for downed trees and powerlines,
as well as power outages. There is also the potential for moderate
to strong north to northeast winds for the LA county coast,
(especially Hollywood Hills, Beverly Hills, and Sepulveda Pass)
extending into Palos Verdes and Catalina Island Tuesday evening
into Wednesday, resulting in the Fire Weather Watch for these
areas. There is a high probability of strong mountain wave wind
conditions during the peak of the event Tuesday afternoon into
Wednesday, which could bring strong/damaging winds to areas that
typically do not see strong winds, including portions of the San
Gabriel Valley and San Fernando Valley. Fire Weather Watches have
been converted to Red Flag Warnings in the Tuesday through
Thursday time frame for areas where there is highest confidence of
reaching critical Red Flag thresholds.


CAZ288-358-362-369>374-376-378-548-062245-
/O.NEW.KLOX.FW.W.0001.250107T1800Z-250110T0200Z/
/O.EXT.KLOX.FW.A.0001.250110T0200Z-250111T0100Z/
Santa Clarita Valley-Central Ventura County Valleys-Malibu Coast-
Western Santa Monica Mountains Recreational Area-
Eastern Santa Monica Mountains Recreational Area-
Calabasas and Agoura Hills-Western San Fernando Valley-
Eastern San Fernando Valley-Southeastern Ventura County Valleys-
Southern Ventura County Mountains-Interstate 5 Corridor-
Los Angeles County San Gabriel Valley-
240 PM PST Sun Jan 5 2025

...RED FLAG WARNING IN EFFECT FROM 10 AM TUESDAY TO 6 PM PST
THURSDAY FOR STRONG/DAMAGING NORTH TO NORTHEAST WINDS AND LOW
RELATIVE HUMIDITY FOR MUCH OF LOS ANGELES AND VENTURA COUNTIES...

...FIRE WEATHER WATCH NOW IN EFFECT FROM THURSDAY EVENING THROUGH
FRIDAY AFTERNOON FOR POTENTIAL WEAK TO MODERATE OFFSHORE WINDS
AND LOW RELATIVE HUMIDITY FOR MUCH OF LOS ANGELES AND VENTURA
COUNTIES...

The National Weather Service in Los Angeles/Oxnard has issued a
Red Flag Warning for strong/damaging north to northeast winds and
low relative humidity, which is in effect from 10 AM Tuesday to 6
PM PST Thursday.

* WINDS...Most Likely Outcome-Strong/damaging north to northeast
  wind event Tuesday afternoon into Wednesday with sustained winds
  of 35 to 55 mph and widespread damaging wind gusts of 50 to 80
  mph. Strongest winds likely in the mountains, foothills, and
  valleys, with isolated gusts of 80 to 100 mph possible for
  favored foothills of the San Fernando/San Gabriel Valleys along
  the Highway 210 corridor from Sylmar/San Fernando eastward to
  foothill communities such as La Crescenta, Altadena, Monrovia,
  and Azusa. Moderate north to northeast winds will likely persist
  Thursday with gusts of 30 to 45 mph, with some weakening
  possible by Friday.

$$


CAZ287-366>368-062245-
/O.CON.KLOX.FW.A.0001.250108T0200Z-250109T0200Z/
Catalina and Santa Barbara Islands-Los Angeles County Beaches-
Palos Verdes Hills-
Los Angeles County Inland Coast including Downtown Los Angeles-
240 PM PST Sun Jan 5 2025

...FIRE WEATHER WATCH REMAINS IN EFFECT FROM TUESDAY EVENING
THROUGH WEDNESDAY AFTERNOON FOR MODERATE TO STRONG NORTH TO
NORTHEAST WINDS AND LOW RELATIVE HUMIDITY FOR LOS ANGELES COAST
EXTENDING INTO PALOS VERDES AND CATALINA ISLAND...

* WINDS...Most Likely Outcome-Moderate to strong north to
  northeast winds Tuesday night into Wednesday with sustained
  winds of 20 to 35 mph and potential damaging wind gusts of 40
  to 60 mph. Strongest winds likely in the Hollywood Hills,
  Beverly Hills, Sepulveda Pass, Palos Verdes extending into
  Catalina Island.

$$
"""

RFW_JAN6_1955Z = """520
WWUS86 KLOX 061955
RFWLOX

URGENT - FIRE WEATHER MESSAGE
National Weather Service Los Angeles/Oxnard CA
1155 AM PST Mon Jan 6 2025

...LIFE THREATENING, DESTRUCTIVE, WIDESPREAD WINDSTORM TUESDAY
AFTERNOON THROUGH WEDNESDAY MORNING FOR PORTIONS OF LOS ANGELES AND
EASTERN VENTURA COUNTIES-- WITH LONG DURATION OF RED FLAG
CONDITIONS INTO THURSDAY-- POSSIBLY EXTENDING INTO FRIDAY...

...RED FLAG WARNINGS IN EFFECT FOR LOS ANGELES COUNTY AND MUCH OF
VENTURA COUNTY---SEE TIMINGS IN HEADLINES BELOW...

...RED FLAG WARNING ISSUED FOR SANTA BARBARA MOUNTAINS INCLUDING
EASTERN SANTA YNEZ RANGE TUESDAY INTO WEDNESDAY...

.Offshore winds are now expected to develop rapidly early Tuesday
morning, leading to an earlier start time of the Red Flag Warning
for many areas. Confidence is high for a life threatening,
destructive, widespread windstorm with dangerous fire weather
conditions Tuesday afternoon through Wednesday morning,
especially focused on the San Gabriel mountains and foothills,
San Gabriel Valley, San Fernando Valley, Hollywood/Beverly Hills,
coastal areas adjacent to the Sepulveda Pass, Simi Valley, and
Santa Monica mountains into Malibu. Strong mountain wave wind
activity will likely impact many of these areas, resulting in very
strong, erratic, and damaging wind gusts, capable of widespread
downed trees/powerlines, as well as widespread power outages. This
windstorm will likely be as destructive as the 2011 windstorm
that impacted Pasadena and nearby San Gabriel Valley foothills.
While the longer duration of strong winds is expected to be
focused across Los Angeles and Ventura counties, there is now
expected to be a shorter duration of Red Flag conditions across
the mountains of Santa Barbara county Tuesday into Wednesday.

Long duration Red Flag Warnings are in effect for much of Los
Angeles and Ventura counties Tuesday through Thursday, with Fire
Weather Watches in effect Thursday night into Friday. This is
a high end Red Flag event. Any new fires will have a high risk
for very rapid fire spread and large fire growth, extreme fire
behavior, and long range spotting.


CAZ287-366>368-070400-
/O.UPG.KLOX.FW.A.0001.250108T0200Z-250109T0200Z/
/O.EXB.KLOX.FW.W.0001.250108T0000Z-250109T0200Z/
Catalina and Santa Barbara Islands-Los Angeles County Beaches-
Palos Verdes Hills-
Los Angeles County Inland Coast including Downtown Los Angeles-
1155 AM PST Mon Jan 6 2025

...RED FLAG WARNING IN EFFECT FROM 4 PM TUESDAY TO 6 PM PST
WEDNESDAY FOR STRONG/DAMAGING WINDS AND LOW RELATIVE HUMIDITY FOR
THE LOS ANGELES COUNTY COAST, PALOS VERDES, AND CATALINA ISLAND...

The National Weather Service in Los Angeles/Oxnard has issued a
Red Flag Warning for strong/damaging winds and low relative
humidity, which is in effect from 4 PM Tuesday to 6 PM PST
Wednesday.

* WINDS...Strong/damaging north to northeast winds from late
  Tuesday afternoon into Wednesday with sustained winds of 25 to
  40 mph and damaging wind gusts of 50 to 60 mph likely. Strongest
  winds likely in the Hollywood Hills, Beverly Hills, coastal
  areas adjacent to Sepulveda Pass, Palos Verdes extending into
  Catalina Island.

$$


CAZ288-358-362-369>374-376-378-548-070400-
/O.EXT.KLOX.FW.W.0001.250107T1200Z-250110T0200Z/
/O.CON.KLOX.FW.A.0001.250110T0200Z-250111T0100Z/
Santa Clarita Valley-Central Ventura County Valleys-Malibu Coast-
Western Santa Monica Mountains Recreational Area-
Eastern Santa Monica Mountains Recreational Area-
Calabasas and Agoura Hills-Western San Fernando Valley-
Eastern San Fernando Valley-Southeastern Ventura County Valleys-
Southern Ventura County Mountains-Interstate 5 Corridor-
Los Angeles County San Gabriel Valley-
1155 AM PST Mon Jan 6 2025

...RED FLAG WARNING NOW IN EFFECT FROM 4 AM TUESDAY TO 6 PM PST
THURSDAY FOR STRONG/DAMAGING NORTH TO NORTHEAST WINDS AND LOW
RELATIVE HUMIDITY FOR MUCH OF LOS ANGELES AND VENTURA COUNTIES...

...FIRE WEATHER WATCH REMAINS IN EFFECT FROM THURSDAY EVENING
THROUGH FRIDAY AFTERNOON FOR POTENTIAL WEAK TO MODERATE OFFSHORE
WINDS AND LOW RELATIVE HUMIDITY FOR MUCH OF LOS ANGELES AND
VENTURA COUNTIES...

* WINDS...Very strong/damaging north to northeast winds Tuesday
  into Wednesday, likely peaking in many areas between Tuesday
  afternoon and Wednesday morning when there is a high risk for
  strong mountain wave wind activity. During this peak, sustained
  winds of 35 to 50 mph and widespread damaging gusts of 50 to 80
  mph can be expected. Strongest winds likely across the Highways
  118 and 210 corridors, including the foothills of the San
  Gabriel/San Fernando Valleys, and Simi Valley where very
  powerful and destructive wind gusts of 80 to 100 mph will be
  likely. Some particular location of greatest concern include
  Sylmar, Porter Ranch, San Fernando eastward to foothill
  communities such as La Crescenta, Altadena, Monrovia, Azusa. and
  Glendora. Moderate north to northeast winds will likely persist
  Thursday with gusts of 30 to 50 mph, with some weakening
  possible by Friday.

$$
"""

RFW_JAN6_2324Z = """188
WWUS86 KLOX 062324
RFWLOX

URGENT - FIRE WEATHER MESSAGE
National Weather Service Los Angeles/Oxnard CA
324 PM PST Mon Jan 6 2025

...PARTICULARLY DANGEROUS SITUATION (PDS) RED FLAG WARNING IN
EFFECT NOON TUESDAY UNTIL 4 PM WEDNESDAY DUE TO DAMAGING NORTH TO
NORTHEAST WINDS AND LOW HUMIDITIES FOR THE FOLLOWING AREAS: SAN
GABRIEL MOUNTAINS/ SAN GABRIEL AND SAN FERNANDO VALLEYS
(ESPECIALLY FOOTHILLS)/ BEVERLY AND HOLLYWOOD HILLS/ COASTAL AREAS
ADJACENT TO SEPULVEDA PASS / SANTA MONICA MOUNTAINS / SANTA SUSANA
MOUNTAINS / MALIBU / EASTERN VENTURA VALLEY (MAINLY NEAR SIMI
VALLEY/MOORPARK) -- THIS WILL LIKELY BE A LIFE THREATENING,
DESTRUCTIVE, AND WIDESPREAD WINDSTORM...

...RED FLAG WARNINGS IN EFFECT FOR LOS ANGELES COUNTY AND MUCH OF
VENTURA COUNTY---SEE TIMINGS IN HEADLINES BELOW...

...RED FLAG WARNING IN EFFECT FOR SANTA BARBARA MOUNTAINS
INCLUDING EASTERN SANTA YNEZ RANGE TUESDAY INTO WEDNESDAY...

***THIS IS A PARTICULARLY DANGEROUS SITUATION (PDS) FOR PORTIONS
OF LOS ANGELES AND VENTURA COUNTIES!***

.A very strong, widespread, and destructive north to northeast
windstorm will bring Extremely Critical fire weather conditions to
many areas of Los Angeles and eastern Ventura counties Tuesday
afternoon into early Wednesday afternoon. This is a PARTICULARLY
DANGEROUS SITUATION (PDS) Red Flag Warning event in many areas,
with the combination of very strong upper level wind support,
tightening offshore pressure gradients (LAX-Daggett peaking at
-7 to -8 mb), and moderate cold air advection. The strongest winds
with this event are expected to be Tuesday afternoon into early
Wednesday afternoon when widespread damaging wind gusts of 50 to
80 mph are likely. The San Gabriel mountains, Santa Susana
mountains, and foothills of the San Gabriel/San Fernando Valleys
will likely see areas of destructive wind gusts between 80 and
100 mph! Due to the very strong upper level wind support and high
risk for strong mountain wave activity, typical wind sheltered
areas such as portions of the LA basin and San Gabriel Valley.
The strong winds will likely result in widespread downed
trees/powerlines, as well as widespread power outages. THIS WILL
LIKELY BE THE MOST DESTRUCTIVE WINDSTORM SEEN SINCE 2011
WINDSTORM THAT DID EXTENSIVE DAMAGE TO PASADENA AND NEARBY
FOOTHILLS OF THE SAN GABRIEL VALLEY. ANY COMMUNITIES ALONG
HIGHWAY 118 AND 210 CORRIDORS WILL BE AT HIGHEST RISK FOR
COMPARABLE WIND DAMAGE. Humidity levels are also expected to
lower to between 10 and 15 percent in many areas by Tuesday
afternoon/evening, potentially lowering into single digits in
some areas by late Tuesday night into Wednesday.

The offshore winds are now expected to arrive early Tuesday
morning, resulting in the Red Flag Warning area being moved up to
4 am Tuesday in many areas. AREAS IN A RED FLAG WARNING
(ESPECIALLY DURING THE PDS TIME FRAME) WILL HAVE INCREASED RISK
FOR LARGE FIRES WITH VERY RAPID FIRE SPREAD, EXTREME FIRE
BEHAVIOR, AND LONG RANGE SPOTTING. While the longer duration of
strong winds and Red Flag conditions is expected to be focused
across Los Angeles and Ventura counties, there is now expected to
be a shorter duration of Red Flag conditions across the mountains
of Santa Barbara county Tuesday into Wednesday. Long duration Red
Flag Warnings are in effect for much of Los Angeles and Ventura
counties Tuesday through Thursday, with Fire Weather Watches in
effect Thursday night into Friday.

CAZ366-368-072000-
/O.EXT.KLOX.FW.W.0001.250107T2000Z-250109T0000Z/
Los Angeles County Beaches-
Los Angeles County Inland Coast including Downtown Los Angeles-
324 PM PST Mon Jan 6 2025

...PARTICULARLY DANGEROUS SITUATION (PDS) RED FLAG WARNING IN EFFECT
FROM NOON TUESDAY UNTIL 4 PM WEDNESDAY DUE TO STRONG/DAMAGING NORTH TO
NORTHEAST WINDS AND LOW HUMIDITIES FOR THE FOLLOWING AREAS:
SAN GABRIEL AND SAN FERNANDO VALLEYS (ESPECIALLY FOOTHILLS)/
BEVERLY AND HOLLYWOOD HILLS/ COASTAL AREAS ADJACENT TO SEPULVEDA
PASS / SANTA MONICA MOUNTAINS / MALIBU / EASTERN VENTURA VALLEY
(MAINLY NEAR SIMI VALLEY/MOORPARK)...

* WINDS...Strong/damaging north to northeast winds from late
  Tuesday afternoon into Wednesday with sustained winds of 25 to
  40 mph and damaging wind gusts of 50 to 60 mph likely. Strongest
  winds likely in the Hollywood Hills, Beverly Hills, and coastal
  areas adjacent to Sepulveda Pass.

$$


CAZ362-369-370-372>374-548-072000-
/O.CON.KLOX.FW.W.0001.250107T1200Z-250110T0200Z/
/O.CON.KLOX.FW.A.0001.250110T0200Z-250111T0100Z/
Malibu Coast-Western Santa Monica Mountains Recreational Area-
Eastern Santa Monica Mountains Recreational Area-
Western San Fernando Valley-Eastern San Fernando Valley-
Southeastern Ventura County Valleys-
Los Angeles County San Gabriel Valley-
324 PM PST Mon Jan 6 2025

...PARTICULARLY DANGEROUS SITUATION (PDS) RED FLAG WARNING IN EFFECT
FROM NOON TUESDAY UNTIL 4 PM WEDNESDAY DUE TO DAMAGING NORTH TO
NORTHEAST WINDS AND LOW HUMIDITIES FOR THE FOLLOWING AREAS:
SAN GABRIEL AND SAN FERNANDO VALLEYS (ESPECIALLY FOOTHILLS)/
BEVERLY AND HOLLYWOOD HILLS/ COASTAL AREAS ADJACENT TO SEPULVEDA
PASS / SANTA MONICA MOUNTAINS / MALIBU / EASTERN VENTURA VALLEY
(MAINLY NEAR SIMI VALLEY/MOORPARK)...RED FLAG WARNING IN EFFECT
FOR ALL OTHER TIMES FROM 4 AM TUESDAY TO 6 PM THURSDAY IN THESE
SAME AREAS...

...FIRE WEATHER WATCH REMAINS IN EFFECT FROM THURSDAY EVENING
THROUGH FRIDAY AFTERNOON FOR POTENTIAL WEAK TO MODERATE OFFSHORE
WINDS AND LOW RELATIVE HUMIDITY FOR MUCH OF LOS ANGELES AND
VENTURA COUNTIES...

* WINDS...Very strong/damaging north to northeast winds Tuesday
  into Wednesday, likely peaking in many areas between Tuesday
  afternoon and Wednesday morning when there is a high risk for
  strong mountain wave wind activity. During this peak, sustained
  winds of 35 to 50 mph and widespread damaging gusts of 50 to 80
  mph can be expected. Strongest winds likely across the Highways
  118 and 210 corridors, including the foothills of the San
  Gabriel/San Fernando Valleys, and Simi Valley where very
  powerful and destructive wind gusts of 80 to 100 mph will be
  likely. Some particular location of greatest concern include
  Sylmar, Porter Ranch, San Fernando, Burbank, Glendale eastward
  to foothill communities such as La Crescenta, Altadena,
  Monrovia, Pasadena, Azusa. and Glendora. Moderate north to
  northeast winds will likely persist Thursday with gusts of 30 to
  50 mph, with some weakening possible by Friday.

$$
"""

RFW_JAN7_2237Z = """312
WWUS86 KLOX 072237
RFWLOX

URGENT - FIRE WEATHER MESSAGE
National Weather Service Los Angeles/Oxnard CA
237 PM PST Tue Jan 7 2025

...PARTICULARLY DANGEROUS SITUATION (PDS) RED FLAG WARNING IN
EFFECT UNTIL 4 PM WEDNESDAY DUE TO DAMAGING NORTH TO NORTHEAST
WINDS AND LOW HUMIDITIES FOR THE FOLLOWING AREAS: SAN GABRIEL
MOUNTAINS/ SAN GABRIEL AND SAN FERNANDO VALLEYS (ESPECIALLY
FOOTHILLS)/ BEVERLY AND HOLLYWOOD HILLS/ COASTAL AREAS ADJACENT TO
SEPULVEDA PASS / SANTA MONICA MOUNTAINS / SANTA SUSANA MOUNTAINS
/ MALIBU / EASTERN VENTURA VALLEY (MAINLY NEAR SIMI
VALLEY/MOORPARK) -- THIS WILL LIKELY BE A LIFE THREATENING,
DESTRUCTIVE, AND WIDESPREAD WINDSTORM...

...RED FLAG WARNINGS IN EFFECT FOR LOS ANGELES COUNTY AND MUCH OF
VENTURA COUNTY---SEE TIMINGS IN HEADLINES BELOW...

...RED FLAG WARNING IN EFFECT FOR SANTA BARBARA MOUNTAINS
INCLUDING EASTERN SANTA YNEZ RANGE INTO WEDNESDAY...

***THIS IS A PARTICULARLY DANGEROUS SITUATION (PDS) FOR PORTIONS
  OF LOS ANGELES AND VENTURA COUNTIES!***

.A very strong, widespread, and destructive north to northeast
windstorm will bring Extremely Critical fire weather conditions
to many areas of Los Angeles and eastern Ventura counties into
early Wednesday afternoon. This is a PARTICULARLY DANGEROUS
SITUATION (PDS) Red Flag Warning event in many areas, with the
combination of very strong upper level wind support, tightening
offshore pressure gradients (LAX-Daggett peaking at - 7 to -8 mb),
and moderate cold air advection. The strongest winds with this
event are expected to be this evening into early Wednesday
afternoon when widespread damaging wind gusts of 50 to 80 mph are
likely. The San Gabriel mountains, Santa Susana mountains, and
foothills of the San Gabriel/San Fernando Valleys will likely see
areas of destructive wind gusts between 80 and 100 mph! Due to the
very strong upper level wind support and high risk for strong
mountain wave activity, typical wind sheltered areas such as
portions of the LA basin and San Gabriel Valley. The strong winds
will likely result in widespread downed trees/powerlines, as well
as widespread power outages. THIS WILL LIKELY BE THE MOST
DESTRUCTIVE WINDSTORM SEEN SINCE 2011 WINDSTORM THAT DID EXTENSIVE
DAMAGE TO PASADENA AND NEARBY FOOTHILLS OF THE SAN GABRIEL
VALLEY. ANY COMMUNITIES ALONG HIGHWAY 118 AND 210 CORRIDORS WILL
BE AT HIGHEST RISK FOR COMPARABLE WIND DAMAGE. Humidity levels are
also expected to lower to between 10 and 20 percent in many areas
by this evening, potentially lowering into single digits in some
areas by Wednesday.

AREAS IN A RED FLAG WARNING (ESPECIALLY DURING THE PDS TIME
FRAME) WILL HAVE INCREASED RISK FOR LARGE FIRES WITH VERY RAPID
FIRE SPREAD, EXTREME FIRE BEHAVIOR, AND LONG RANGE SPOTTING. Long
duration Red Flag Warnings are in effect for much of Los Angeles
and Ventura counties Tuesday through Thursday, with Fire Weather
Watches in effect Thursday night into Friday. There is a shorter
duration of Red Flag conditions across the mountains of Santa
Barbara county into Wednesday.

CAZ362-369-370-372>374-548-110100-
/O.CON.KLOX.FW.W.0001.000000T0000Z-250110T0200Z/
/O.CON.KLOX.FW.A.0001.250110T0200Z-250111T0100Z/
Malibu Coast-Western Santa Monica Mountains Recreational Area-
Eastern Santa Monica Mountains Recreational Area-
Western San Fernando Valley-Eastern San Fernando Valley-
Southeastern Ventura County Valleys-
Los Angeles County San Gabriel Valley-
237 PM PST Tue Jan 7 2025

...RED FLAG WARNING REMAINS IN EFFECT UNTIL 6 PM PST THURSDAY FOR
THE FOLLOWING AREAS: SAN GABRIEL AND SAN FERNANDO VALLEYS
(ESPECIALLY FOOTHILLS)/ BEVERLY AND HOLLYWOOD HILLS/ COASTAL
AREAS ADJACENT TO SEPULVEDA PASS / SANTA MONICA MOUNTAINS /
MALIBU / EASTERN VENTURA VALLEY (MAINLY NEAR SIMI
VALLEY/MOORPARK)...RED FLAG WARNING IN EFFECT FOR ALL OTHER TIMES
THROUGH 6 PM THURSDAY IN THESE SAME AREAS... ...FIRE WEATHER
WATCH REMAINS IN EFFECT FROM THURSDAY EVENING THROUGH FRIDAY
AFTERNOON FOR POTENTIAL WEAK TO MODERATE OFFSHORE WINDS AND LOW
RELATIVE HUMIDITY FOR MUCH OF LOS ANGELES AND VENTURA COUNTIES...

* WINDS...Very strong/damaging north to northeast winds into
  Wednesday, likely peaking in many areas between this afternoon
  and Wednesday morning when there is a high risk for strong
  mountain wave wind activity. During this peak, sustained winds
  of 35 to 50 mph and widespread damaging gusts of 50 to 80 mph
  can be expected. Strongest winds likely across the Highways 118
  and 210 corridors, including the foothills of the San
  Gabriel/San Fernando Valleys, and Simi Valley where very
  powerful and destructive wind gusts of 80 to 100 mph will be
  likely. Some particular location of greatest concern include
  Sylmar, Porter Ranch, San Fernando, Burbank, Glendale eastward
  to foothill communities such as La Crescenta, Altadena,
  Monrovia, Pasadena, Azusa. and Glendora. Moderate north to
  northeast winds will likely persist Thursday with gusts of 30 to
  50 mph, with some weakening possible by Friday.

$$


CAZ366-368-090000-
/O.CON.KLOX.FW.W.0001.000000T0000Z-250109T0000Z/
Los Angeles County Beaches-
Los Angeles County Inland Coast including Downtown Los Angeles-
237 PM PST Tue Jan 7 2025

...RED FLAG WARNING REMAINS IN EFFECT UNTIL 4 PM PST WEDNESDAY
FOR THE FOLLOWING AREAS: SAN GABRIEL AND SAN FERNANDO VALLEYS
(ESPECIALLY FOOTHILLS)/ BEVERLY AND HOLLYWOOD HILLS/ COASTAL
AREAS ADJACENT TO SEPULVEDA PASS / SANTA MONICA MOUNTAINS /
MALIBU / EASTERN VENTURA VALLEY (MAINLY NEAR SIMI
VALLEY/MOORPARK)...

* WINDS...Strong/damaging north to northeast winds from late
  Tuesday afternoon into Wednesday with sustained winds of 25 to
  40 mph and damaging wind gusts of 50 to 60 mph likely.
  Strongest winds likely in the Hollywood Hills, Beverly Hills,
  and coastal areas adjacent to Sepulveda Pass.

$$
"""
