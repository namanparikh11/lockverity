# Code signing policy

- Lockverity v2.1.2 is currently unsigned.
- The Windows installer and the PE executables distributed inside the portable package are currently unsigned. The portable ZIP itself does not receive Authenticode signing.
- Lockverity is preparing an application to the SignPath Foundation Open Source code-signing program. There is no current SignPath-signed Lockverity release.
- If the application is accepted, attribution will read: "Free code signing provided by SignPath.io, certificate by SignPath Foundation".
- Committer/reviewer: Naman Parikh ([@namanparikh11](https://github.com/namanparikh11)).
- Signing approver: Naman Parikh ([@namanparikh11](https://github.com/namanparikh11)).
- [Privacy policy](privacy.md).

No SignPath integration, credential, signing workflow, or definitive artifact configuration is present today. Checksums belong in generated manifests or release metadata produced from final distributable artifacts; an immutable source tag is not moved to embed a later artifact hash.
