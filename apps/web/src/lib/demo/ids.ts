/**
 * Quote IDs of the static demo. GitHub Pages can only serve pages generated at
 * build time, so every /quotes/[id] page the demo can ever show is pre-rendered:
 * the captured seed quotes plus a fixed pool for quotes created in the browser
 * (generate from RFQ, re-parse).
 */
import seed from "@/lib/demo/seed.json";

export const QUOTE_ID_POOL = [
  "18fe8e8a-25ea-4bf7-97a9-8fb0343fce18",
  "0b9ad6e5-cfc9-4561-8668-8823f8f2fc4b",
  "12cd5b74-d0c8-49a1-be2e-95683832c70f",
  "f6015e7c-238b-4f4e-9dbd-f143f7994b57",
  "d9818534-5b47-418c-a122-81a8afea9b55",
  "121d316e-c79d-489b-8617-a77ccc0881e8",
  "644591d6-da10-40e4-845a-306e88ce6b64",
  "33291dff-694e-43a5-b0e5-3db0586f4d47",
  "a0d4b552-1c3c-44c6-9981-8980fd0351e2",
  "609dbaa3-9d8c-4c41-9564-1f80f5ae5d41",
  "9e44de54-138d-4723-a3b6-887e5f1680b5",
  "c449aa6e-2620-452b-976c-d3131361a58f",
  "51493e79-608d-4632-be2a-1f996f7792bf",
  "2241e8fd-bdbc-4374-a8d1-fe7970f0db45",
  "d70738bd-dbb7-4d78-b835-5f50656d81bd",
  "1f31575c-50e9-4e43-a776-7b486b5beafd",
  "2cd899e3-acde-4b33-a675-5d77bc17f803",
  "5c5a039f-406d-4460-9757-be0393a692a7",
  "00b0cae7-e7e8-4791-abfd-4db62aa7c84b",
  "bc654df0-697e-4337-b933-8df4ab9ad85f",
  "08a1226c-4a32-406c-a954-7c7a5b036bdf",
  "5a2826ee-e6a3-4ceb-9d70-b0885e5e6abd",
  "ace04883-8e3e-4dac-ad01-1deaef0739d0",
  "94b33bce-1d14-4f61-8d49-906b8119afd0",
  "a17eaf84-607a-496d-9912-e4b6d1dcf207",
  "3b4312ee-3522-48b8-8f03-a87ecc70d16b",
  "8aabae04-2425-4482-b597-f69cf4c414bd",
  "264ae8a3-2fd8-44f9-8f88-780c845e6741",
  "3a1771c9-5ca4-4b24-bd6c-837171e72f28",
  "88d76a96-add0-4388-ae23-050725fca65b",
  "c2569b08-ea35-4d19-ad4a-798b63ef175e",
  "9f72e23d-e0ff-490f-b2c0-986e22573b7d",
  "1c428da1-0965-4512-91ce-78387b4a7be8",
  "1055ff7e-6637-46fa-85d9-ba87a74c6843",
  "df902fc1-dc76-412a-9b9b-c08277844523",
  "027602b9-067f-418d-b486-e0cef779ab16",
  "100fcfe6-01c5-40a8-88f8-6de71b360e1c",
  "0969528f-e357-47c0-825b-f4739828a28f",
  "f8044777-c29d-4aa8-8ee9-287e245dcfc0",
  "2f3a4f2d-5669-4a0e-bc22-9c8b84872b38",
] as const;

export function demoQuoteIds(): string[] {
  return [...seed.quotes.map((q) => q.id), ...QUOTE_ID_POOL];
}
