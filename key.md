To add a readonly, restricted key for GitHub and also use it as an ssh key for CloudLab, start by making a new directory, and then create a new key:

```
ssh-keygen -t ed25519 -C "ae key"
```

and store it in the new directory. Copy the public key (the contents of the `.pub` file that was created alongside the new key).

Make a new empty GitHub repository, go to the repository's "Settings", "Deploy keys", and select "Add deploy key", give the key a name and paste the public key in the "Key" field.

Now go to cloudlab, click on your username in the top right, select "Manage SSH Keys" and paste the public key in the "Key" field.

If you will be using a container, use the path of the directory created in the first step when bind-mounting the key directory. In either case (container or Ubuntu 22.04) you will need to `ssh-add` this new key, as described in the main [README](README.md): you can now go there and continue with the further steps.
