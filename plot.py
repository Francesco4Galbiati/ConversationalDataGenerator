import matplotlib.pyplot as plt

data = {
    "one-to-one": {"unspecified_slot": 40},
    "one-to-many": {"unspecified_slot": 10},
    "many-to-one": {"unspecified_slot": 37},
    "many-to-many": {"unspecified_slot": 9},
}

labels = list(data.keys())
values = [v["unspecified_slot"] for v in data.values()]

plt.figure()
plt.bar(labels, values)

plt.xlabel("Approach")
plt.ylabel("Unspecified slot count")
plt.title("Unspecified Slots per Approach")

plt.tight_layout()
plt.show()