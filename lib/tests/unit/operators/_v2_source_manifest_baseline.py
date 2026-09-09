"""Baseline values for the v2.8 operator-lifecycle change, frozen at 2.7.0
(``b1dad86103528a0e05fa235b0eb4f0b506d49592``).

Literals only, so ``test_source_manifest_amendment_scope`` never reads Git history at run
time. v2.8 may recompute the 14 digests named by ``DISCOVERY_MUTABLE_PATHS`` and
``OUTCOME_MUTABLE_PATHS``; every other value here is an expectation v2.8 must satisfy
rather than rewrite.
"""

from __future__ import annotations

from typing import Final

BASELINE_COMMIT: Final = "b1dad86103528a0e05fa235b0eb4f0b506d49592"

# The four plan-producing operators v2.8 deprecates. Editing them moves their source digests.
DEPRECATION_COHORT: Final[tuple[str, ...]] = (
    "multipart_query",
    "nl2query_router",
    "plan_discover",
    "query_breakdown",
)

# The lifecycle contract: both registered versions of each cohort operator are deprecated,
# and none of the other 64 cards is. Written from the v2.8 specification, not read from the
# registry.
DEPRECATED_OPERATOR_IDS: Final[frozenset[str]] = frozenset(
    {
        "multipart_query@1.0.0",
        "multipart_query@2.0.0",
        "nl2query_router@1.0.0",
        "nl2query_router@2.0.0",
        "plan_discover@1.0.0",
        "plan_discover@2.0.0",
        "query_breakdown@1.0.0",
        "query_breakdown@2.0.0",
    }
)

# The only values v2.8 may move, as key paths into each fixture.
DISCOVERY_MUTABLE_PATHS: Final[tuple[tuple[str, ...], ...]] = (
    ("source_manifest", "files", "multipart_query"),
    ("source_manifest", "files", "nl2query_router"),
    ("source_manifest", "files", "plan_discover"),
    ("source_manifest", "files", "query_breakdown"),
    ("source_manifest", "aggregate_sha256"),
)

OUTCOME_MUTABLE_PATHS: Final[tuple[tuple[str, ...], ...]] = (
    ("source_manifest", "files", "multipart_query"),
    ("source_manifest", "files", "nl2query_router"),
    ("source_manifest", "files", "plan_discover"),
    ("source_manifest", "files", "query_breakdown"),
    ("source_manifest", "aggregate_sha256"),
    ("rows", "multipart_query", "source_sha256"),
    ("rows", "nl2query_router", "source_sha256"),
    ("rows", "plan_discover", "source_sha256"),
    ("rows", "query_breakdown", "source_sha256"),
)

# sha256 of src/blue_data_ops/operators/<name>_operator.py for the 32 modules v2.8 must
# not touch. The guard recomputes them from the working tree.
UNAFFECTED_SOURCE_SHA256: Final[dict[str, str]] = {
    "argmax": "5301be8c01d34ef890f4d94cba1738ab13cdcf053c0c3521ba4b08d28ff29b9a",
    "argmin": "080a1148c5aa5e2db0517ea7b2427cd75d9575884efa2d2b626ca7042913b600",
    "avg": "2ffc1e520e7ce1d65c9c030bdfbf6921f37bfcd97f3d8a66689437b66477c82d",
    "classify": "f4550001f0cef86bb5a7b27dc2dd30c73830b458d6a4ce6bb30649314b6d0b49",
    "cluster": "2ac4fdbbf672da3cdc0b50bce4f3ad712a877609dd5f493ba2a02d43a650babf",
    "create_database": "ce5eb3429058756222d6cd93b7d26e80ff4a904898ab2375b22ddfed71d12277",
    "create_table": "13a3fb1922b4d882212df5b274c757bb2a4159414405cee12ef766efe5e17a4c",
    "data_discover": "36c6e5b4a11d2795ab2de2a4bc57940a3ec9ddc87efb189fba7d0e7b17cb8771",
    "delete": "ab33f67a6e072192556a493d6e8570735c28417e74b3590b666621c0bc64cd02",
    "insert": "5b77700cb7a1d56b7e57fd38e73f833da89ab382e17753a6f2e2383b001e7e32",
    "insert_table": "8737a51c3055df4d8d5f55bc5f7e45d767393506c403a3fcc09814b40696db84",
    "intersect": "08b04aac356d9935778653b98b22acbdd5d48a7dfd6a6dfa7fa085a9a16241a9",
    "join": "c28ff17ee207b271a671a054f5585c7606d5b8773d4b0b892a5965bd8d272401",
    "max": "5d9a4d2de8b402ca848e5553a726deeff18c18d28a54d4cb96b4ac2c61c6e4e2",
    "min": "5ad7edbfc06b5d61af50c29c9255b48825679f94ca856bf9a4e0b631aa7a9c5c",
    "nl2bn": "2f7d03c95a7d330a18f5ae1f593fb820559a6a17fd927c137a530707c1556a31",
    "nl2llm": "123b9b10041d9c89dadc0ad3abae25e3fef65e9397fbf8729c743c618ff564f4",
    "nl2sql": "24e45552027691d0e1da3f526e9fe4a49af92a112c0ff5c5aeecd2b024df5b73",
    "normalize_text": "3ba875420c503489f90865e655ea5494161be9cec59eff6702d259470db43014",
    "project": "ededc1a16f129310f44047b1fa013624ebc4d466c619d4712d1cb1583c239000",
    "segment_text": "8565aa50bed2e1124ee0d29b041453debbb05a89aac9fdc0323482eb64297153",
    "select": "a4bf4e0bbd01c959ff075ba7e2a9737ff615c3fd8e945eaa2704adcf19e5e24c",
    "semantic_extract": "bcd21ac95965245564c7dd77d054e71de22bb245f47c264595e26a8efe0c9a9e",
    "semantic_filter": "6c84a8124dabc1d7bdc981fbca98a18149174d5a59aba9ab29323459d37e5e5f",
    "semantic_join": "d0ac8f4392ee9b8c6cf876a5e65f96258a477aed2343ad8d41a1d8a751e3e157",
    "semantic_project": "cfb78fef257f905931a1b96cfa3245b5648201e436764c6de16d7e972056cc64",
    "semantic_transform": "328292737735a6e7cad47a3d1bd347facd4175cb01726896add23d65b5a63360",
    "sum": "57de9ac53c365356fa76ed8eb4e1968a9342daabb172eaeadcb934dafabbfeac",
    "union": "b08bffdd9a6bb397c7764e68fec8e41f103b4404338ce2b2c7a71baccd2fe95b",
    "vector_embed": "6a15fe204e50c63b343f9f991c844077fc8a6a86b7550268a4805ea9820288af",
    "vector_search": "aa5b5888540919f12408e7cdf48af2cdb663139023818cee845021616a2dea60",
    "vector_similarity": "4d8b0ef97c175fce63cf3554611f3752b62d6d69ba545dd4053a79b76cef163a",
}

# v2_discovery_catalog.json, per top-level key. `source_manifest` is digested with the
# four cohort file digests and the aggregate removed; `cards` is covered below.
DISCOVERY_SECTION_SHA256: Final[dict[str, str]] = {
    "card_count": "8722616204217eddb39e7df969e0698aed8e599ba62ed2de1ce49b03ade0fede",
    "namespaces": "25db5b3f9a0ada7668d83e7f7387ef9450f3b11061c95c9964ce549f09818809",
    "operator_count": "76a50887d8f1c2e9301755428990ad81479ee21c25b43215cf524541e0503269",
    "registry": "3e976b43ff63a407ff6dfde82399734b355b5d58e5520b3866d5201b896f77f9",
    "schema_version": "adb9b96cb270dbe9d64b653ed700d5490e047e1bd54720a5144414f84638c10a",
    "source_manifest": "c6aadc29b19cd8fad82a15f4dd49c30b4d92ff65108cb0c0ffa412162467ae29",
    "text_weights": "9b04f3a1758156fe6fda781a1db23a75586025a9a1bb6c98cc4612bd33b1de53",
}

# One digest per catalog card, with the `deprecated` key removed, so the value stays
# comparable to its 2.7.0 form. The lifecycle flags are pinned by DEPRECATED_OPERATOR_IDS.
DISCOVERY_CARD_SHA256: Final[dict[str, str]] = {
    "argmax@1.0.0": "3017c38e853b48abaad32c80c149c8a4e78a2ea7cb5d3af336f963753ed7ffb6",
    "argmax@2.0.0": "5196155ade751cb4eb50296757638a33452237ac6a4e6a5543d9076ac7f51c5a",
    "argmin@1.0.0": "5f38ab0cad08eff8a0d1a219076e632b1cab811d3e5f64691eebd90122c28e44",
    "argmin@2.0.0": "8545a3b32546d864f3c6806c4e8a0f640768a0601bede5892a54198ea90a6da1",
    "avg@1.0.0": "51014e8ab957a25c3bff1803cdc66fa08cd798d30f6fa1da4fce0f0b5c8a4f30",
    "avg@2.0.0": "1b8049cd0f6170592524d99fef84cba64c1c296caf067553edfdc278b373af12",
    "classify@1.0.0": "adbe0e97f7a1aef4baf73da92c0353509acb70b760a16dfaeeefcf9db3f01d02",
    "classify@2.0.0": "4c619b1b551c2ce6a8ecd0d5f874fd36e91def8f2fed69afd7e4b1cb465f45ef",
    "cluster@1.0.0": "0f19d1c10781978f47e96f5c2c12428a0e495c54b0553c05c239e8139da3f432",
    "cluster@2.0.0": "402992ee2a2c4c22b1bd2ef6b7925d0a84a4f694b61fb4257dd2ff5668ad6e37",
    "create_database@1.0.0": "e60f81cc65e812aea43f1d154d81dadf705963605e78bdac0bdc884a7d1dfbb3",
    "create_database@2.0.0": "31cb11b10371dc8fe3cd9e687a4eed1319aa85bfd79dfdafccb03f1cd3f2db45",
    "create_table@1.0.0": "ed9d83d9021df3d55a54829e17e4dd0277ca32f6d13c603e398226a209eee94a",
    "create_table@2.0.0": "752b36d987973159a3fb0505f9ffe0b6a77944d696441890c6a789bff0994523",
    "data_discover@1.0.0": "5bc95e422b578a376a6c866ceafcb9e860d397bfe3f100fdf35b9ec70141bab3",
    "data_discover@2.0.0": "b1a6d65e684d92477f56361bafb90bf1cd98b43c871c430d459e9925e94b9d28",
    "delete@1.0.0": "0eb02154a4b59b74287b9a2667011a02e3aeaacdb2f329749f02c4d956c8fbe5",
    "delete@2.0.0": "0a440bfe31eadb1507610d9123d54d0e95cd2e3f5a46d6e262fc09fc4d9a9eeb",
    "insert@1.0.0": "525d568b923fb8c843757c212cb00d7fa0efd82f6a18f120cfd43d608200c84a",
    "insert@2.0.0": "bcae03271d9a833f0f61adcd664a59ff64cc5ec3ed0ad9e7138d2be8a040c06b",
    "insert_table@1.0.0": "d509b07da03cb3fcb0f821ffcabd307fcc4d9c794dc20f9cc652199f1ce4e6c9",
    "insert_table@2.0.0": "3a5ba6b32f837c9e582fb0025c14913175f55ec103898c6824878aec4db15527",
    "intersect@1.0.0": "5797e88b42bc1932de8bb8b31a3e9b18687f9b76576e04820826cf43a39fc37d",
    "intersect@2.0.0": "633b365d84a9a331846f3ba05df4329dd255652616b0d43451ad21a243cdeeb2",
    "join@1.0.0": "c71bf7e31ca6214d666b99de8a2831e10a57b7e19ce9b865fa77748aba58f272",
    "join@2.0.0": "a734298effb41e4e07eb364c8def6d42e904d7ca206a135265bcc59e461723f1",
    "max@1.0.0": "0e92f7643b091cfecd75f08b37d69acb6e872d8666a9306710b6b5d3c2a49e45",
    "max@2.0.0": "0b4939890d4ba38a58d89a87d4a3594ce2fca2402bdabfb1c41b9e5345880e64",
    "min@1.0.0": "3954c2dc7aff20b05be32cbec46f49d15eed7a5d95f0af447239835c13f921e1",
    "min@2.0.0": "d4d6ff2b5fc6883ca9469cb581373b370da8b2b497bc620ff0adab12bc5e810d",
    "multipart_query@1.0.0": "88033505a346b7d5575d31fb692c203018065b1a2432c9f7f281515f417ac9df",
    "multipart_query@2.0.0": "d9a60cf6563f8431191d167aff2b85358a72401ebda1a7751a4b488bf3a6fd54",
    "nl2bn@1.0.0": "c84b14ebca6515df08accb5d67339303fbe621475f964fc360f991e9fbc7cc73",
    "nl2bn@2.0.0": "fbafacb767dffeb4f4bdc5b48f4b5bada602a494fa8d3bab1b47b8c27c481404",
    "nl2llm@1.0.0": "4126a2c78924e27b98a7eb45288481b0344c7597e7cf19ad891d4825f821a3fd",
    "nl2llm@2.0.0": "0f493d388ba25ce673d1549cf7d9d95a3094123919b608f3e13bae1b874f56a4",
    "nl2query_router@1.0.0": "0225f21d802dfc4016915f27d42570c532af458b2234ff5b7faa310071d627ee",
    "nl2query_router@2.0.0": "3890b6adc3c930d85a710aab8fdd09dca98e26493c2af82d7109cdc3a2e1e760",
    "nl2sql@1.0.0": "329fb29047c3a1a9534f5bd7f36126a647764eaecd3eaaa5c4924a18d6589240",
    "nl2sql@2.0.0": "4ee52eb03500cf2a9d752f68ea6857a573096a1e657e245921a38cbe9ebe41b4",
    "normalize_text@1.0.0": "19ed63ed962b00f82d6fb2afdbcd7c1ed6f8ea87b517f3ccb8a4e853f8f8aa12",
    "normalize_text@2.0.0": "61501985bef42cc65a631393875e7dc1d3c32cbed5d1978f7ae2fa739f565cec",
    "plan_discover@1.0.0": "7927f731e98fa2ad96390fbbeacdd1fbb88c290df95633202a011120a70745c2",
    "plan_discover@2.0.0": "91cfa8d80565eb338892683d64ae66dca010edcb077d7701865306b2de5c55f9",
    "project@1.0.0": "045fc307aa07f099f6df7462ae10c54575a59e40c9044dc8d6d6db68cafd0bb3",
    "project@2.0.0": "d9dd39f2423c650ae561b5dafd4e581e77dbfe6c6a932763c0a4831313311651",
    "query_breakdown@1.0.0": "b914f4bed1770cd677d71aedaea2e4801838a9be31396c08f9ddc9e434092097",
    "query_breakdown@2.0.0": "5d020544c4f56f2d348888f50b706750ced545affd2e5798637491adccb315ad",
    "segment_text@1.0.0": "1c3656f59c63ecf0eeaeac82f4f65c14242b1fd3586f695042b6352909968ea2",
    "segment_text@2.0.0": "82d0b79ade6fc8abac6687beb6ce996ad748f95249d65f696b38e92f6501e5fe",
    "select@1.0.0": "98e8a0143c9bfeb2067b8b33e3dd5d44da23936b48c8f3fb6b5b3d84a87319f4",
    "select@2.0.0": "6098088afe04581909e9d3d9d9e42c230b1767ea3343e02e81ffb5ea73723d39",
    "semantic_extract@1.0.0": "49485764d7e678cae14072dc309a606b43c7c436a1645e9e92039f7bd75b63f4",
    "semantic_extract@2.0.0": "4fb38638265d5eb5d0335a201f32cd7b4b65a50f959d6c45bda09b0a241751f4",
    "semantic_filter@1.0.0": "483fe1f7629e9f4827b60b21239a2f25bd3b5117913dd463e82b852a395c461e",
    "semantic_filter@2.0.0": "af2a388ab0efd5a887d707c055f40dbeeac0740a2134452cf33080b8a503c1ee",
    "semantic_join@1.0.0": "db8c98fd14f136efde2937ec0a446ef79072363fe23df941cc173d6ff3761ac2",
    "semantic_join@2.0.0": "7c3a668d27170e8c040214945404046be7a6a0f8e736980f6271151e9d93171e",
    "semantic_project@1.0.0": "779bcdb935d9ea134f329ddd7d716a8e38b19e1a361c2f3addc763de9df5a724",
    "semantic_project@2.0.0": "a97e380ff53d1ce926d934cc9eeda87293b27fe08cb0dc5f28abd3b5b2cedc54",
    "semantic_transform@1.0.0": "63f1f4175ffc9690779d6c6590894f76eca3edf98ce78dc755f94ec310df708c",
    "semantic_transform@2.0.0": "519c90e69e2a7fa3763592772fb812e8dff18b6521a4730f688a7744a852aefb",
    "sum@1.0.0": "2c27fca5b8baafc10867e3826784fbdf6bfb44b5f40bbf6f479b17e544f5d3ee",
    "sum@2.0.0": "f4366fe27c9a78f15403ca9b69ce48e16b8b1331f1f3742729050951e15cf1b2",
    "union@1.0.0": "13646b93ca245fc06ddbf12888cd019ee41f0034a05712b9d9abe7d009a7b6e2",
    "union@2.0.0": "faf700d23327a0302040c9c35db97230ba6620f1aa47e2654e3826f000bb5a4e",
    "vector_embed@1.0.0": "ad1a084cdbfd9388cb875d8907c7d44f4857392d73fa85f9d98db3fcb40e0fdd",
    "vector_embed@2.0.0": "109d287eb388c7f01ea79817a58f84b7bf9efba47096ba2189ccfe5481863456",
    "vector_search@1.0.0": "415c49c0b8c155bb09ed47e6849e916aa7b0977eb3b185e3c75b6221d9fb8cf9",
    "vector_search@2.0.0": "2e10f03dd6b7b2a81e8adc00415938fbf49576c2d8abaef46a83c1ada305ee9e",
    "vector_similarity@1.0.0": "be557253201eb4f5bda07f5b84a9891715a783178b674aaadb16322150fc24cc",
    "vector_similarity@2.0.0": "adbbbe01b28be4ddb724feefe4262475eda490bf3a691e86fce78a4442b661e2",
}

# v2_operator_outcomes.json, per top-level key, `source_manifest` redacted as above and
# `rows` covered below.
OUTCOME_SECTION_SHA256: Final[dict[str, str]] = {
    "operator_count": "76a50887d8f1c2e9301755428990ad81479ee21c25b43215cf524541e0503269",
    "registry": "3e976b43ff63a407ff6dfde82399734b355b5d58e5520b3866d5201b896f77f9",
    "registry_names_sha256": "d8fa99a38bed742ca09ca118120fee0a0b40e099fc2a8ec1a03a89d750673f61",
    "schema_version": "06803f9b6c89a4c501efd86098e03dbe8bcb8a84329b4225f2051dde6a6268c0",
    "shared_rules": "f18f1bfc43008b08fee6bb06690ea1854f90ba705ab2d70625a89bea13e85aa0",
    "source_manifest": "c6aadc29b19cd8fad82a15f4dd49c30b4d92ff65108cb0c0ffa412162467ae29",
    "timeout_representatives": "1ff83a8a59c4778a1934ce8ad07e1c09ccb1c7f06b6e6f464cdb0e1cadcec82c",
}

# One digest per outcome row: every case, expectation, and note. The four cohort rows are
# digested without `source_sha256`; the other 32 keep it.
OUTCOME_ROW_SHA256: Final[dict[str, str]] = {
    "argmax": "a2657b934eaa41f9a74bd9b8fc9e1ca53c929073f7b893692d0dc293f01f1dd8",
    "argmin": "f8e4b833ab98d7bfdbf09ca2d8d6beb1ea46f17ac043d402a8bc22f19a99d0b7",
    "avg": "bc71becd1daa0592f44b9c1770fc0697c41c9523da2c2836c48e283e14053489",
    "classify": "52172d6764a886308a52385b32a1a8ca14f7d6e50a56231405c5d56375f4819d",
    "cluster": "a24887048bc7feb1996e3ccfce51f61fabc27785f386303f626d48e91455fde2",
    "create_database": "d02b06d3b195e6fd7ebeab05ec5fa454b6a820b303880dae7d6e24f43969ad25",
    "create_table": "5f0bdd4625d2c6d4e3c789432319ef8ceb4f47a1b12ac937efadca2c9f98fe68",
    "data_discover": "875431cc9e787da4f53cadc2ed52e8578f988e9579cafe45dbf942eb34aa6b92",
    "delete": "821e12932826600ee57c778f8d4722b4a19594b56aad7b2170e4774e05ca5ef2",
    "insert": "26ed8971cba5bf7785967d1cdd7854ad141b5e2b283c324452d9c229827c3b38",
    "insert_table": "59600f122c4762692d64b11f415845d6e6455d137180ded20c1d9d396978c3cb",
    "intersect": "1f0d216361f2dcb8dc18e99166435d18346b9c30790a24205ab055d926afc11f",
    "join": "00c3e11ddf79c4ae17e2595c5b3b4f670e166aea420945664830d9bdaf5594bb",
    "max": "8a1be06bfde67fc2898d7e3a19807d509b37429177eb97f8197148c8fa22ea0e",
    "min": "d7ccefa0d5c8234530b3155365f1e48c2ce132dfdf601e7c12719e8d93dafd6e",
    "multipart_query": "cb4ce988057759dac4080fcd6b109633ee2de070611586deb17fbf4a2abbf4d8",
    "nl2bn": "2c72e8829292117087d97014400f9cf703b84819f138cf445d96bc532f30833b",
    "nl2llm": "7fc8ae47d1c99c1f2ee013fe69819e3aa3d26acc48c44210dd4c05037e34e40b",
    "nl2query_router": "6f86ae92ad6b1e89c4f5d7a38660e30e44dc06fcff5e9b53f2dea00159db0811",
    "nl2sql": "c3e5a50d6e29ac0eedcb295c60206475032f8e41b2eab38001fccadf14cbc626",
    "normalize_text": "a00291ce8567a596360fbe4f995eac638181ec3402552341c26dc3f5fb31c0fb",
    "plan_discover": "1a28853bda48d7cabc8568a6cac02f77d5dc54b555086ba32fc2a3230f8917c1",
    "project": "3701c34f501e0f675626aee1faa970ee2073ff771613c34391a4112d51a92b67",
    "query_breakdown": "8cc3b6317bb44bbf25e7e4f785b3b71c16710d4960d40e48b9c9dbe25b269516",
    "segment_text": "92883bebafcbd0a9f220b7048e2320a4936845eaaee1fa452c2a410e2f33a065",
    "select": "30de7f68025924a6701fc6dee4cf2ce41e4355a36abb6ffa15261383c658e0ed",
    "semantic_extract": "e45c1d5ed3ecbbb9760e7ef2424b18c101660fcf3ee341f6828cbf3c800e887f",
    "semantic_filter": "c0905eb24a98a8e2e0af428a8b7c16bbdfcdd81d34239d7d8edb941a5800cdca",
    "semantic_join": "4c38c247e948e17f789d96ca08de9c9372ecf76c386d4a4543a9abfb37d7a9b3",
    "semantic_project": "ad982ae2868d71f7acab80db80b686ffc57debcffe3adff8dbad093618ef4ea6",
    "semantic_transform": "4ddafff45c0abc0b52b57925de23df7d648af8257a8157ae79dc0791c747c95d",
    "sum": "cefe024f6f354dd67badfd289be3cc7eab034cf23b5fc24c5af74c05e75f721c",
    "union": "a593ff114d4187c640e5fba544a8c0e108fccf28c30e5b44916c6b2cd58fe5ed",
    "vector_embed": "698dbdb8bdbf5376047cbb8a0b34a3b0be16d98709a7d2e0d8dadb1910d44cd0",
    "vector_search": "20b01912db38f28c78ad30c58a32fc3b0222843a61117f05bcbf8f7b7e2e0b59",
    "vector_similarity": "4af7c0ffe3b470f9923284476d128ce9e3ef5c581bce06264354a0b2a5a3de99",
}
