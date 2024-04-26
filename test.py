ich_bin_eine_variable_denn_ich_kann_mich_ändern = 12

print(ich_bin_eine_variable_denn_ich_kann_mich_ändern)

ich_bin_eine_variable_denn_ich_kann_mich_ändern += 1

print(ich_bin_eine_variable_denn_ich_kann_mich_ändern)


ich_bin_viele = ["erster!", "zweiter!", "leckt mich!", "allerletzter scheiss!"]

print("len: "+str(len(ich_bin_viele)))

#print(ich_bin_viele[1])

#for i in range(0, len(ich_bin_viele)):
#    print(i)
#    print(str(i)+": "+ich_bin_viele[i])
    
i = 0
while True:
    print(str(i)+": "+ich_bin_viele[i])
    i += 1
    
    if i >= len(ich_bin_viele):
        break
    else:
        print("noch nicht durch!!!")
    
print("************************")    
    
ich_mit_namen = {
    "mama": "melli",
    "lieblingsschwester": "mara",
    "mein_name": "johanna",
    "vorgefahrten": {
        "opa": "opapopa",
        "oma": "ekapeka"
        }
    }


ich_mit_namen["vorgefahrten"]["uroma"] = "hedda"

print(ich_mit_namen["vorgefahrten"]["uroma"])


def hi(ichbineinargument):
    return "pups von: "+str(ichbineinargument)

wertausfunktion = hi("Aika")

print(wertausfunktion)

