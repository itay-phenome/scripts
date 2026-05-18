import boto3
import json
import copy

# --- Configuration (DEFINE HERE) ---
SOURCE_PROFILE = "default"
TARGET_PROFILE = "ews-mum"
SOURCE_REGION = "ap-south-1"
DEST_REGION = "us-east-1"
SCOPE = "REGIONAL"  # or "CLOUDFRONT"
SRC_WEBACL_NAME = "phenome"
SRC_WEBACL_ID = "83268fa4-afe3-4ab9-99fb-9fa49b09284f"
DST_WEBACL_NAME = "phenome-clone"
ATTACH_TO_RESOURCE_ARN = ""  # e.g. "arn:aws:elasticloadbalancing:...", or leave empty

# --- Init clients ---
session_src = boto3.Session(profile_name=SOURCE_PROFILE, region_name=SOURCE_REGION)
session_dst = boto3.Session(profile_name=TARGET_PROFILE, region_name=DEST_REGION)

waf_src = session_src.client('wafv2')
waf_dst = session_dst.client('wafv2')

# --- Helpers ---
def find_existing(waf_client, kind, name):
    if kind == "IPSet":
        items = waf_client.list_ip_sets(Scope=SCOPE)['IPSets']
    elif kind == "RegexPatternSet":
        items = waf_client.list_regex_pattern_sets(Scope=SCOPE)['RegexPatternSets']
    elif kind == "RuleGroup":
        items = waf_client.list_rule_groups(Scope=SCOPE)['RuleGroups']
    else:
        return None
    for item in items:
        if item['Name'] == name:
            return item['ARN']
    return None

def copy_resource(kind, ref):
    name = ref['Name']
    existing_arn = find_existing(waf_dst, kind, name)
    if existing_arn:
        print(f"[!] {kind} already exists: {name} – using existing ARN")
        return existing_arn

    if kind == "IPSet":
        get = waf_src.get_ip_set(Name=name, Scope=SCOPE, Id=ref['Id'])
        spec = copy.deepcopy(get['IPSet'])
        for k in ['ARN', 'Id', 'Tags']:
            spec.pop(k, None)
        new = waf_dst.create_ip_set(
            Name=spec['Name'], Scope=SCOPE,
            Description=spec.get('Description', ''),
            IPAddressVersion=spec['IPAddressVersion'],
            Addresses=spec['Addresses']
        )
        print(f"[+] Cloned IPSet: {name}")
        return new['Summary']['ARN']

    elif kind == "RegexPatternSet":
        get = waf_src.get_regex_pattern_set(Name=name, Scope=SCOPE, Id=ref['Id'])
        spec = copy.deepcopy(get['RegexPatternSet'])
        for k in ['ARN', 'Id', 'Tags']:
            spec.pop(k, None)
        new = waf_dst.create_regex_pattern_set(
            Name=spec['Name'], Scope=SCOPE,
            Description=spec.get('Description', ''),
            RegularExpressionList=spec['RegularExpressionList']
        )
        print(f"[+] Cloned RegexPatternSet: {name}")
        return new['Summary']['ARN']

    elif kind == "RuleGroup":
        get = waf_src.get_rule_group(Name=name, Scope=SCOPE, Id=ref['Id'])
        spec = copy.deepcopy(get['RuleGroup'])
        for k in ['ARN', 'Id', 'Tags']:
            spec.pop(k, None)
        new = waf_dst.create_rule_group(
            Name=spec['Name'], Scope=SCOPE,
            Description=spec.get('Description', ''),
            Capacity=get['RuleGroup']['Capacity'],
            Rules=spec['Rules'],
            VisibilityConfig=spec['VisibilityConfig']
        )
        print(f"[+] Cloned RuleGroup: {name}")
        return new['Summary']['ARN']

# --- Step 1: Export WebACL ---
webacl = waf_src.get_web_acl(Name=SRC_WEBACL_NAME, Scope=SCOPE, Id=SRC_WEBACL_ID)['WebACL']
print(f"[+] Exported WebACL: {webacl['Name']} with {len(webacl['Rules'])} rules")

# --- Step 2: Clean ---
for key in ['Id', 'ARN', 'LockToken', 'Capacity', 'Tags']:
    webacl.pop(key, None)
webacl['Name'] = DST_WEBACL_NAME

# --- Step 3: Patch ---
def patch_statement(statement):
    if 'IPSetReferenceStatement' in statement:
        arn = statement['IPSetReferenceStatement']['ARN']
        parts = arn.split('/')
        new_arn = copy_resource("IPSet", {"Name": parts[-2], "Id": parts[-1]})
        statement['IPSetReferenceStatement']['ARN'] = new_arn

    elif 'RegexPatternSetReferenceStatement' in statement:
        arn = statement['RegexPatternSetReferenceStatement']['ARN']
        parts = arn.split('/')
        new_arn = copy_resource("RegexPatternSet", {"Name": parts[-2], "Id": parts[-1]})
        statement['RegexPatternSetReferenceStatement']['ARN'] = new_arn

    elif 'RuleGroupReferenceStatement' in statement:
        arn = statement['RuleGroupReferenceStatement']['ARN']
        parts = arn.split('/')
        new_arn = copy_resource("RuleGroup", {"Name": parts[-2], "Id": parts[-1]})
        statement['RuleGroupReferenceStatement']['ARN'] = new_arn

    elif 'AndStatement' in statement:
        for s in statement['AndStatement']['Statements']:
            patch_statement(s)
    elif 'OrStatement' in statement:
        for s in statement['OrStatement']['Statements']:
            patch_statement(s)
    elif 'NotStatement' in statement:
        patch_statement(statement['NotStatement']['Statement'])

for rule in webacl['Rules']:
    patch_statement(rule['Statement'])

# --- Step 4: Create WebACL ---
try:
    result = waf_dst.create_web_acl(
        Name=DST_WEBACL_NAME,
        Scope=SCOPE,
        DefaultAction=webacl['DefaultAction'],
        Description=webacl.get('Description', ''),
        Rules=webacl['Rules'],
        VisibilityConfig=webacl['VisibilityConfig']
    )
    new_arn = result['Summary']['ARN']
    print(f"[✓] Created WebACL in destination: {new_arn}")
except Exception as e:
    print("[!] Failed to create WebACL:", e)
    exit(1)

# --- Step 5: Optional Attach ---
if ATTACH_TO_RESOURCE_ARN:
    try:
        waf_dst.associate_web_acl(
            WebACLArn=new_arn,
            ResourceArn=ATTACH_TO_RESOURCE_ARN
        )
        print(f"[✓] Attached WebACL to: {ATTACH_TO_RESOURCE_ARN}")
    except Exception as e:
        print("[!] Failed to attach WebACL:", e)