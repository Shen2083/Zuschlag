"""A lightweight stand-in for an SAP ERP system, for end-to-end tests and `make demo`.

* Outbound (SAP -> Zuschlag): pushes MATMAS05 / DEBMAS06 IDocs to Zuschlag's
  inbound endpoints, as an SAP "XML HTTP" port (SM59 type G) would.
* Inbound (Zuschlag -> SAP): receives ORDERS05 at `/sap/bc/idoc_xml`, checks it
  like the receiving SAP system would (control record, partner, known customer
  and materials, quantities) and acknowledges it with an ALEAUD01 audit message:
  status 06 (received, syntax OK), then 53 (quotation posted) or 51 (error).

It is deliberately independent of `zuschlag_api`: its master data comes from
the IDoc files it "owns" (by default the customer's sample files), so it checks
Zuschlag's output rather than agreeing with it by construction.
"""

from tests.mock_sap.push import push_master_data
from tests.mock_sap.server import MockSap, MockSapConfig, create_app

__all__ = ["MockSap", "MockSapConfig", "create_app", "push_master_data"]
