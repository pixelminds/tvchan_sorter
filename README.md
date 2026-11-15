# tvchan_sorter
Download your channel list from your not-so-smart TV, and sort your channels on excel (CSV). This is a Python script to convert to/from the native TLL format (which is basically XML).
Usage: 
- Export channel list from TV. 
- Extract list from xml using ```python3 tll_channels.py export GlobalClone00001.TLL channels.csv```
- Edit channel.csv – you can change numbers and names, keep the rest as is. If you just want to reorder rows, you don't need to change numbers
- Import using ```python3 tll_channels.py apply GlobalClone00001.TLL channels_m.csv new.TLL``` (add `--by-row` if you reordered rows)
- Rename new.TLL to GlobalClone00001.TLL, and import to TV. 
Been tested with an LG webOS TV, but should work with other brands or models.