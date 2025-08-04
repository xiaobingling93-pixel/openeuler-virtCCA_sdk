#  Encrypting and Decrypting Container Images <a name="EN-US_TOPIC_0000002208690114"></a>

1.  Use Skopeo to encrypt the image.

    1.  Set the IP address and port of the key provider.

        ```
        cd /home/work
        cat <<EOF > ocicrypt.conf
        {
          "key-providers": {
            "attestation-agent": {
              "grpc": "${ip}:${port}"
        }}}
        EOF
        ```

    2.  Generate a random key on the server where the key provider is located.

        ```
        head -c32 < /dev/random > /home/work/keys/key1
        ```

    3.  Use Skopeo to encrypt the image and push it to the local image repository.

        ```
        export ENC_KEY_FILE="/home/work/keys/key1"
        export OCICRYPT_KEYPROVIDER_CONFIG="$(pwd)/ocicrypt.conf"
        skopeo copy --insecure-policy --encryption-key provider:attestation-agent:keypath=${ENC_KEY_FILE} docker://registry.hw.com:5000/busybox:latest docker://registry.hw.com:5000/busybox_enc:latest
        ```

    >![](public_sys-resources/icon-note.gif) **NOTE:** 
    >-   The encryption key is generated in the environment where the key provider is located, and Skopeo specifies the key path on the remote end.
    >-   Ensure that the key provider and KBS have been enabled.

2.  Deploy the encrypted image.
    1.  Deploy the encrypted image and write the pod configuration.

        ```
        vim enc-test.yaml
        ```

    2.  Add the following content to the configuration file:

        ```
        apiVersion: v1
        kind: Pod
        metadata:
          name: enc-test
        spec:
          runtimeClassName: kata
          containers:
          - name: box
            image: registry.hw.com:5000/busybox_enc:latest
        ```

    3.  Deploy the pod.

        ```
        kubectl apply -f enc-test.yaml
        ```

    4.  Check whether the image is decrypted and whether the container is running properly.

        ```
        kubectl get pods
        ```

        >![](public_sys-resources/icon-note.gif) **NOTE:** 
        >If an image signature policy is configured, you need to sign the encrypted image. For details, see  [Verifying Signatures of Container Images](en-us_topic_0000002044282114.md).

