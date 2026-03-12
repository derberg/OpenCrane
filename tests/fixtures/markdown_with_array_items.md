# Array Items Chunking Test

This fixture tests recursive chunking of arrays with items containing properties.

```yaml
$schema: https://json-schema.org/draft/2020-12/schema
type: object
title: Volume Configuration Schema
description: Schema demonstrating array items recursive chunking
properties:
  volumes:
    type: array
    description: |
      Array of volume configurations for storage management. Each volume
      represents a distinct storage unit with mounting options, size specifications,
      security settings, and backup policies. Volumes can be dynamically provisioned
      or statically defined. This property demonstrates how large array schemas with
      nested item properties are recursively chunked to stay within token limits.
      The chunking process evaluates the entire array definition including the items
      schema. When the combined token count exceeds 800 tokens and the items schema
      contains properties, the chunker recursively processes each property within
      the items schema as separate chunks. This ensures that even complex array
      definitions remain granular and searchable at the property level while
      maintaining semantic coherence within each chunk.
    items:
      type: object
      description: |
        Individual volume configuration with detailed specifications for mounting,
        storage allocation, and operational parameters. Each volume item must specify
        a unique name, mount path, and size. Additional properties control caching,
        encryption, backup schedules, and performance characteristics.
      properties:
        name:
          type: string
          description: |
            Unique identifier for the volume within the cluster. Must follow DNS-1123
            naming conventions with lowercase alphanumeric characters and hyphens only.
            Maximum length of 63 characters. The name is used for volume references in
            pod specifications and must be unique within the namespace.
          pattern: ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$
          maxLength: 63
        path:
          type: string
          description: |
            Absolute path where the volume will be mounted within the container filesystem.
            Must start with a forward slash and follow POSIX path conventions. The path
            must not conflict with system directories or other volume mount points. Common
            patterns include /data, /mnt/volumes, or application-specific paths like
            /var/lib/mysql for database storage.
          pattern: ^/[a-zA-Z0-9_/-]*$
        size:
          type: string
          description: |
            Storage capacity specification using Kubernetes resource notation. Supports
            units: Ki (kibibytes), Mi (mebibytes), Gi (gibibytes), Ti (tebibytes),
            Pi (pebibytes). Examples: "10Gi", "500Mi", "1Ti". The specified size is the
            minimum guaranteed capacity; actual provisioned size may be larger depending
            on storage class and provisioner configuration.
          pattern: ^[0-9]+(Ki|Mi|Gi|Ti|Pi)$
        accessMode:
          type: string
          description: |
            Volume access mode defining how the volume can be mounted by pods. ReadWriteOnce
            allows mounting by a single node with read-write access. ReadOnlyMany allows
            mounting by multiple nodes with read-only access. ReadWriteMany allows mounting
            by multiple nodes with read-write access. Choice depends on storage backend
            capabilities and application requirements.
          enum:
            - ReadWriteOnce
            - ReadOnlyMany
            - ReadWriteMany
        storageClass:
          type: string
          description: |
            Storage class name for dynamic provisioning. References a StorageClass resource
            that defines the provisioner, parameters, and reclaim policy. Common examples
            include "standard", "fast-ssd", "network-storage". If omitted, the cluster's
            default storage class is used. Must match an existing StorageClass in the cluster.
        encrypted:
          type: boolean
          description: |
            Enable encryption at rest for the volume. When true, data written to the volume
            is encrypted using the storage backend's encryption mechanism. Encryption keys
            are typically managed by the cloud provider's KMS or a cluster-local key management
            system. Encryption adds minimal performance overhead while providing data security
            compliance.
          default: false
        backup:
          type: object
          description: |
            Backup configuration for the volume including schedule, retention, and destination.
            Backups are performed using volume snapshots and stored according to the specified
            policy. Critical for disaster recovery and data protection strategies.
          properties:
            enabled:
              type: boolean
              description: Enable automated backups for this volume
              default: false
            schedule:
              type: string
              description: |
                Cron expression defining backup schedule. Examples: "0 2 * * *" (daily at 2 AM),
                "0 */6 * * *" (every 6 hours). Uses standard cron syntax with minute, hour,
                day of month, month, and day of week fields.
              pattern: ^(\*|[0-9,\-/]+)\s+(\*|[0-9,\-/]+)\s+(\*|[0-9,\-/]+)\s+(\*|[0-9,\-/]+)\s+(\*|[0-9,\-/]+)$
            retention:
              type: integer
              description: |
                Number of backup snapshots to retain. Older snapshots beyond this count are
                automatically deleted. Minimum value of 1 ensures at least one backup is always
                available. Typical values range from 7 (daily backups for a week) to 30+ for
                monthly retention.
              minimum: 1
              default: 7
```
